"""`serve` supervises one `starpulse worker <context>` child per context: restarts it with growing delay, stops it with serve."""

import itertools
import logging
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import starpulse._internal.server.rss as rss_module
import starpulse._internal.server.supervisor as supervisor_module
from starpulse._internal.config.config import Forward, MemoryLimit, load
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
        replace(load(None), delivery_worker=True, runs_worker=True, history_worker=True), Path("/etc/starpulse.toml")
    )
    neither = worker_commands(
        replace(
            load(None),
            delivery_worker=True,
            autopilot_worker=True,
            runs_worker=True,
            forwarding_worker=True,
            history_worker=True,
        ),
        None,
    )

    assert every["pulls"] == [sys.executable, "-m", "starpulse", "worker", "pulls"]
    assert every["runs"] == [sys.executable, "-m", "starpulse", "worker", "runs"]
    assert every["history"] == [sys.executable, "-m", "starpulse", "worker", "history"]
    assert set(every) == {"pulls", "autopilot", "runs", "history"}  # forwarding has no child without a [forward] table
    assert only_autopilot == {
        "autopilot": [sys.executable, "-m", "starpulse", "worker", "autopilot", "--config", "/etc/starpulse.toml"]
    }
    assert neither == {}


def test_the_history_child_runs_for_a_false_setting_and_never_beside_a_hub() -> None:
    assert "history" in worker_commands(load(None), None)
    assert "history" not in worker_commands(replace(load(None), history_worker=True), None)
    assert "history" not in worker_commands(load(None), None, hub=True)  # a hub keeps its history threads in-process


def test_the_forwarding_child_runs_only_for_a_config_with_a_forward_table_and_a_false_setting() -> None:
    forwarding = replace(load(None), forward=Forward("https://hub.example.test", "HUB_TOKEN"))

    assert worker_commands(forwarding, None)["forwarding"] == [
        sys.executable,
        "-m",
        "starpulse",
        "worker",
        "forwarding",
    ]
    assert "forwarding" not in worker_commands(replace(forwarding, forwarding_worker=True), None)
    assert "forwarding" not in worker_commands(load(None), None)


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


MB = 1024 * 1024


class Sized(Spawned):
    """A stand-in `Popen` that stays running until terminated or killed, with a resident size the test sets."""

    def __init__(self, command: list[str]) -> None:
        super().__init__(command)
        self.killed = False

    def poll(self) -> int | None:
        return 1 if self.terminated or self.killed else None

    def kill(self) -> None:
        self.killed = True


def _limited(sizes: dict[int, int], **kwargs) -> Supervisor:
    Spawned.made = []
    return Supervisor(
        {"pulls": SLEEP},
        spawn=Sized,
        limits={"pulls": MemoryLimit(100, 200)},
        rss=lambda pid: sizes[pid] * MB,
        sample_every=1.0,
        **kwargs,
    )


def test_a_child_past_its_soft_limit_is_replaced_by_a_new_one_before_the_old_one_is_stopped(caplog) -> None:
    sizes = {1000: 50}
    supervisor = _limited(sizes)
    supervisor.tick(0.0)
    sizes[1000] = 150
    sizes[1001] = 10
    with caplog.at_level(logging.WARNING):
        supervisor.tick(1.0)

    old, new = Spawned.made
    assert old.terminated
    assert not new.terminated
    assert supervisor.pids() == {"pulls": new.pid}
    assert "worker pulls" in caplog.text
    assert "soft" in caplog.text


def test_a_child_past_its_hard_limit_is_killed_and_started_again(caplog) -> None:
    sizes = {1000: 50, 1001: 10}
    supervisor = _limited(sizes)
    supervisor.tick(0.0)
    sizes[1000] = 250
    with caplog.at_level(logging.WARNING):
        supervisor.tick(1.0)

    old, new = Spawned.made
    assert old.killed
    assert supervisor.pids() == {"pulls": new.pid}
    assert "worker pulls" in caplog.text
    assert "hard" in caplog.text


def test_a_child_is_sampled_no_oftener_than_the_interval() -> None:
    sizes = {1000: 50, 1001: 10}
    supervisor = _limited(sizes)
    supervisor.tick(0.0)
    sizes[1000] = 250
    supervisor.tick(0.5)

    assert len(Spawned.made) == 1


def test_without_an_rss_reader_one_warning_is_logged_and_children_run_unlimited(caplog) -> None:
    Spawned.made = []
    supervisor = Supervisor({"pulls": SLEEP}, spawn=Sized, limits={"pulls": MemoryLimit(1, 2)}, rss=None)
    with caplog.at_level(logging.WARNING):
        supervisor.tick(0.0)
        supervisor.tick(10.0)
        supervisor.tick(20.0)

    assert len(Spawned.made) == 1
    assert caplog.text.count("memory limits are not enforced") == 1


def test_this_platform_reads_a_live_processs_resident_size() -> None:
    reader = rss_module.rss_reader()
    assert reader is not None
    assert reader(os.getpid()) > MB
