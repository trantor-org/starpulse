"""`serve` supervises one `starpulse worker <context>` child per context: restarts it with growing delay, stops it with serve."""

import itertools
import logging
import os
import socket
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import starpulse.runtime.memory as memory_module
import starpulse.runtime.supervisor as supervisor_module
from starpulse.board.model.search_config import Search
from starpulse.runtime.config import MemoryLimit, load
from starpulse.runtime.hold import LISTEN_FD_ENV
from starpulse.runtime.supervisor import Supervisor, spawn_child, worker_commands

from tests.supervised import running_pids

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
    only_delivery_and_scheduler = worker_commands(
        replace(
            load(None),
            runs_worker=True,
            flow_metrics_worker=True,
            board_worker=True,
            api_worker=True,
        ),
        Path("/etc/starpulse.toml"),
    )

    assert every["pulls"] == [sys.executable, "-m", "starpulse", "worker", "pulls"]
    assert every["runs"] == [sys.executable, "-m", "starpulse", "worker", "runs"]
    assert every["flow-metrics"] == [sys.executable, "-m", "starpulse", "worker", "flow-metrics"]
    assert set(every) == {"api", "pulls", "scheduler", "runs", "flow-metrics", "board"}
    assert only_delivery_and_scheduler == {
        context: [sys.executable, "-m", "starpulse", "worker", context, "--config", "/etc/starpulse.toml"]
        for context in ("pulls", "scheduler")
    }


def test_the_flow_metrics_child_runs_for_a_false_setting() -> None:
    assert "flow-metrics" in worker_commands(load(None), None)
    assert "flow-metrics" not in worker_commands(replace(load(None), flow_metrics_worker=True), None)


def test_the_board_child_runs_for_a_false_setting() -> None:
    assert "board" in worker_commands(load(None), None)
    assert "board" not in worker_commands(replace(load(None), board_worker=True), None)


def test_the_search_child_runs_only_for_an_embeddings_url_and_a_false_setting() -> None:
    embedding = replace(load(None), search=Search("http://embeddings.test/v1/embeddings", "m"))

    assert "search" in worker_commands(embedding, None)
    assert "search" not in worker_commands(load(None), None)  # no endpoint, nothing to embed
    assert "search" not in worker_commands(replace(embedding, search_worker=True), None)


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
    supervisor = Supervisor({"pulls": SLEEP, "scheduler": SLEEP}, spawn=Spawned)
    supervisor.tick(0.0)

    supervisor.stop()
    supervisor.tick(1000.0)

    assert [child.terminated for child in Spawned.made] == [True, True]


def test_killing_a_child_yields_a_replacement_with_a_new_pid() -> None:
    supervisor = Supervisor({"pulls": SLEEP}, first_delay=0.05, poll=0.02)
    supervisor.start()
    try:
        first = _wait_for(lambda: running_pids(supervisor).get("pulls"))
        subprocess.run(["kill", "-9", str(first)], check=True)

        second = _wait_for(lambda: (pid := running_pids(supervisor).get("pulls")) not in (None, first) and pid)

        assert second != first
        assert _alive(second)
    finally:
        supervisor.stop()


def test_stopping_the_supervisor_leaves_no_child_running() -> None:
    supervisor = Supervisor({"pulls": SLEEP, "scheduler": SLEEP}, poll=0.02)
    supervisor.start()
    pids = _wait_for(lambda: len(running_pids(supervisor)) == 2 and list(running_pids(supervisor).values()))

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
        memory=lambda pid: sizes[pid] * MB,
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
    assert running_pids(supervisor) == {"pulls": new.pid}
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
    assert running_pids(supervisor) == {"pulls": new.pid}
    assert "worker pulls" in caplog.text
    assert "hard" in caplog.text


def test_a_limited_child_that_exited_is_not_sampled_while_it_waits_to_start_again() -> None:
    supervisor = _limited({1000: 50, 1001: 10})
    supervisor.tick(0.0)
    Spawned.made[0].terminated = True

    supervisor.tick(1.5)  # exits, then waits out its restart delay with no process to sample

    assert running_pids(supervisor) == {}


def test_a_child_is_sampled_no_oftener_than_the_interval() -> None:
    sizes = {1000: 50, 1001: 10}
    supervisor = _limited(sizes)
    supervisor.tick(0.0)
    sizes[1000] = 250
    supervisor.tick(0.5)

    assert len(Spawned.made) == 1


def test_a_limited_child_that_exits_at_startup_is_restarted_after_its_delay() -> None:
    sizes = {1000: 10, 1001: 10}
    supervisor = _limited(sizes, first_delay=5.0)
    supervisor.tick(0.0)
    Spawned.made[0].terminated = True  # it exited during startup, as a worker meeting a locked database does

    supervisor.tick(2.0)  # noted dead, due at +5s, and sampled while it waits
    supervisor.tick(7.0)

    assert running_pids(supervisor) == {"pulls": 1001}


def test_without_a_memory_reader_one_warning_is_logged_and_children_run_unlimited(caplog) -> None:
    Spawned.made = []
    supervisor = Supervisor({"pulls": SLEEP}, spawn=Sized, limits={"pulls": MemoryLimit(1, 2)}, memory=None)
    with caplog.at_level(logging.WARNING):
        supervisor.tick(0.0)
        supervisor.tick(10.0)
        supervisor.tick(20.0)

    assert len(Spawned.made) == 1
    assert caplog.text.count("memory limits are not enforced") == 1


def test_this_platform_reads_a_live_processs_resident_size() -> None:
    reader = memory_module.memory_reader()
    assert reader is not None
    assert reader(os.getpid()) > MB


def test_the_api_child_runs_for_a_false_setting() -> None:
    config = Path("/etc/starpulse.toml")

    assert worker_commands(load(None), config)["api"] == [
        sys.executable,
        "-m",
        "starpulse",
        "worker",
        "api",
        "--config",
        str(config),
    ]
    assert "api" not in worker_commands(replace(load(None), api_worker=True), None)


def test_a_child_started_without_a_socket_is_told_of_none(tmp_path: Path) -> None:
    seen = tmp_path / "env"
    child = spawn_child(
        [
            sys.executable,
            "-c",
            "import os, sys; open(sys.argv[1], 'w').write(os.environ.get('" + LISTEN_FD_ENV + "', 'none'))",
            str(seen),
        ]
    )
    assert child.wait(20) == 0
    assert seen.read_text() == "none"


class Handed:
    """A stand-in `Popen` that stays running and records the socket it was started with."""

    made: list[Handed] = []

    def __init__(self, command: list[str], listening: socket.socket | None = None) -> None:
        self.command = command
        self.listening = listening
        self.pid = 3000 + len(self.made)
        self.ended = False
        self.made.append(self)

    def poll(self) -> int | None:
        return 0 if self.ended else None

    def terminate(self) -> None:
        self.ended = True

    def kill(self) -> None:
        self.ended = True

    def wait(self, timeout: float | None = None) -> int:
        return 0


def test_the_supervisor_hands_its_socket_to_the_named_child_each_time_it_starts_it() -> None:
    Handed.made = []
    with socket.socket() as listening:
        supervisor = Supervisor({"api": SLEEP, "pulls": SLEEP}, spawn=Handed, sockets={"api": listening})
        supervisor.tick(0.0)
        Handed.made[0].ended = True  # the api child dies; the next tick starts its replacement
        supervisor.tick(5.0)  # notes the exit; the restart waits out its delay
        supervisor.tick(10.0)

    handed = [child.listening for child in Handed.made]
    assert len(Handed.made) == 3
    assert handed.count(None) == 1  # pulls never holds the page's socket
    assert handed.count(listening) == 2


class Beside(Handed):
    """A `Handed` that holds the readiness pipe like a child that inherited it, and says whether its predecessor still ran."""

    report = True

    def __init__(self, command: list[str], listening: socket.socket | None = None, ready: int | None = None) -> None:
        self.predecessor_ended = Beside.made[-1].ended if Beside.made else None
        self.ready = os.dup(ready) if ready is not None else None
        if self.ready is not None and Beside.report:
            os.write(self.ready, b"1")
        super().__init__(command, listening)

    def close(self) -> None:
        if self.ready is not None:
            os.close(self.ready)


def test_replacing_the_listening_child_starts_the_new_one_and_waits_for_it_before_ending_the_old_one() -> None:
    Beside.made, Beside.report = [], True
    with socket.socket() as listening:
        supervisor = Supervisor({"api": SLEEP}, spawn=Beside, sockets={"api": listening}, warm=5.0)
        supervisor.tick(0.0)
        old = Beside.made[0]
        assert supervisor._replace("api", supervisor._children["api"]) == "replaced"

    new = Beside.made[1]
    new.close()
    assert old.ended
    assert not new.ended
    assert new.predecessor_ended is False  # the old child was still running when the new one started


def test_replacing_the_listening_child_ends_the_old_one_after_the_bound_when_the_new_one_never_reports() -> None:
    Beside.made, Beside.report = [], False
    with socket.socket() as listening:
        supervisor = Supervisor({"api": SLEEP}, spawn=Beside, sockets={"api": listening}, warm=0.3)
        supervisor.tick(0.0)
        started = time.monotonic()
        supervisor._replace("api", supervisor._children["api"])

    Beside.made[1].close()
    assert Beside.made[0].ended
    assert time.monotonic() - started >= 0.3
