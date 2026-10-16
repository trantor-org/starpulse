"""`serve` supervises one `starpulse worker <context>` child per context: restarts it with growing delay, stops it with serve."""

import itertools
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import starpulse._internal.server.supervisor as supervisor_module
from starpulse._internal.config.config import load
from starpulse._internal.server.supervisor import Supervisor, worker_commands

STEP = 0.25
SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]


class Spawned:
    """A stand-in `Popen` that exits at once, so every `tick` finds it dead."""

    made: list[Spawned] = []

    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.pid = 1000 + len(self.made)
        self.terminated = False
        self.made.append(self)

    def poll(self) -> int:
        return 1

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 1


def _alive(pid: int) -> bool:
    return subprocess.run(["ps", "-p", str(pid)], capture_output=True).returncode == 0


def _wait_for(check, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found := check():
            return found
        time.sleep(0.02)
    raise AssertionError("condition not reached")


def test_a_context_whose_worker_setting_is_false_gets_a_child_command_and_a_true_one_gets_none() -> None:
    every = worker_commands(load(None), None)
    only_autopilot = worker_commands(
        replace(load(None), delivery_worker=True, runs_worker=True), Path("/etc/starpulse.toml")
    )
    neither = worker_commands(replace(load(None), delivery_worker=True, autopilot_worker=True, runs_worker=True), None)

    assert every["pulls"] == [sys.executable, "-m", "starpulse", "worker", "pulls"]
    assert every["runs"] == [sys.executable, "-m", "starpulse", "worker", "runs"]
    assert set(every) == {"pulls", "autopilot", "runs"}
    assert only_autopilot == {
        "autopilot": [sys.executable, "-m", "starpulse", "worker", "autopilot", "--config", "/etc/starpulse.toml"]
    }
    assert neither == {}


def test_a_child_that_exits_repeatedly_is_restarted_after_a_growing_delay() -> None:
    Spawned.made = []
    supervisor = Supervisor({"pulls": SLEEP}, spawn=Spawned, first_delay=1.0, longest_delay=4.0, stable_after=60.0)

    starts = []
    now = 0.0
    while len(Spawned.made) < 5 and now < 100:
        before = len(Spawned.made)
        supervisor.tick(now)
        if len(Spawned.made) > before:
            starts.append(now)
        now += STEP

    # each gap is the delay plus the tick that noticed the exit
    assert [b - a - STEP for a, b in itertools.pairwise(starts)] == [1.0, 2.0, 4.0, 4.0]


def test_a_child_that_ran_stably_restarts_at_once_and_resets_the_delay() -> None:
    Spawned.made = []
    supervisor = Supervisor({"pulls": SLEEP}, spawn=Spawned, first_delay=5.0, longest_delay=60.0, stable_after=10.0)

    supervisor.tick(0.0)  # started
    supervisor.tick(20.0)  # it died after running 20s: stable, so no delay
    supervisor.tick(20.0)

    assert len(Spawned.made) == 2


def test_stop_ends_every_child_and_nothing_restarts_after_it() -> None:
    Spawned.made = []
    supervisor = Supervisor({"pulls": SLEEP, "autopilot": SLEEP}, spawn=Spawned)
    supervisor.tick(0.0)

    supervisor.stop()
    supervisor.tick(1000.0)

    assert [child.terminated for child in Spawned.made] == [True, True]


def test_killing_a_child_yields_a_replacement_with_a_new_pid() -> None:
    supervisor = Supervisor({"pulls": SLEEP}, first_delay=0.05, poll=0.02)
    supervisor.start()
    try:
        first = _wait_for(lambda: supervisor.pids().get("pulls"))
        subprocess.run(["kill", "-9", str(first)], check=True)

        second = _wait_for(lambda: (pid := supervisor.pids().get("pulls")) not in (None, first) and pid)

        assert second != first
        assert _alive(second)
    finally:
        supervisor.stop()


def test_stopping_the_supervisor_leaves_no_child_running() -> None:
    supervisor = Supervisor({"pulls": SLEEP, "autopilot": SLEEP}, poll=0.02)
    supervisor.start()
    pids = _wait_for(lambda: len(supervisor.pids()) == 2 and list(supervisor.pids().values()))

    supervisor.stop()

    assert not any(_alive(pid) for pid in pids)


def test_the_supervisor_module_uses_no_fork_fcntl_or_proc() -> None:
    source = Path(supervisor_module.__file__).read_text()

    assert not any(word in source for word in ("os.fork", "fcntl", "/proc/"))
