"""A supervised worker child ends with `serve`: when it is killed, and when a terminal interrupt reaches its process group.

Each case runs with the child started by `subprocess` and, on Linux, forked from the preloaded process."""

import os
import signal
import subprocess
import sys
import time

import pytest
from starpulse.runtime.zygote import fork_supported


def _alive(pid: int) -> bool:
    return subprocess.run(["ps", "-p", str(pid)], capture_output=True).returncode == 0


def _wait_for(check, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found := check():
            return found
        time.sleep(0.02)
    raise AssertionError("condition not reached")


HOLD = [
    sys.executable,
    "-c",
    "import threading; from starpulse.runtime.hold import hold; hold(threading.Event(), print)",
]
FORKED = [sys.executable, "-m", "starpulse", "hold"]
DRIVER = """
import sys, time
from starpulse.runtime.supervisor import Supervisor, spawn_child
from starpulse.runtime.zygote import Forker
from tests.supervised import running_pids
forker = Forker([], entry="tests.zygote_entry:main")
spawn = forker if sys.argv[1] == "forked" else spawn_child
supervisor = Supervisor({"w": sys.argv[2:]}, spawn=spawn, poll=0.02)
supervisor.start()
try:
    print(running_pids(supervisor)["w"], flush=True)
    time.sleep(60)
except KeyboardInterrupt:
    pass
finally:
    supervisor.stop()
    forker.close()
"""

STARTS = [
    pytest.param("subprocess", HOLD, id="subprocess"),
    pytest.param(
        "forked", FORKED, id="forked", marks=pytest.mark.skipif(not fork_supported(), reason="no preloaded fork here")
    ),
]


def _driver(how: str, command: list[str]) -> tuple[subprocess.Popen, int]:
    driver = subprocess.Popen(
        [sys.executable, "-c", DRIVER, how, *command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    return driver, int(driver.stdout.readline())


@pytest.mark.parametrize(("how", "command"), STARTS)
def test_a_child_exits_when_the_supervisor_is_killed(how: str, command: list[str]) -> None:
    driver, child = _driver(how, command)
    try:
        driver.kill()
        driver.wait()

        assert _wait_for(lambda: not _alive(child))
    finally:
        subprocess.run(["kill", "-9", str(child)], capture_output=True)


@pytest.mark.parametrize(("how", "command"), STARTS)
def test_a_terminal_interrupt_to_the_process_group_stops_the_supervisor_with_no_traceback(
    how: str, command: list[str]
) -> None:
    driver, child = _driver(how, command)

    os.killpg(driver.pid, signal.SIGINT)
    _, err = driver.communicate(timeout=15)

    assert not _alive(child)
    assert err == ""
