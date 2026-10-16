"""A supervised worker child ends with `serve`: when it is killed, and when a terminal interrupt reaches its process group."""

import os
import signal
import subprocess
import sys
import time


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
    "import threading; from starpulse._internal.server.hold import hold; hold(threading.Event(), print)",
]
DRIVER = """
import sys, time
from starpulse._internal.server.supervisor import Supervisor
supervisor = Supervisor({"w": sys.argv[1:]}, poll=0.02)
supervisor.start()
try:
    print(supervisor.pids()["w"], flush=True)
    time.sleep(60)
except KeyboardInterrupt:
    pass
finally:
    supervisor.stop()
"""


def _driver() -> tuple[subprocess.Popen, int]:
    driver = subprocess.Popen(
        [sys.executable, "-c", DRIVER, *HOLD],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    return driver, int(driver.stdout.readline())


def test_a_child_exits_when_the_supervisor_is_killed() -> None:
    driver, child = _driver()
    try:
        driver.kill()
        driver.wait()

        assert _wait_for(lambda: not _alive(child))
    finally:
        subprocess.run(["kill", "-9", str(child)], capture_output=True)


def test_a_terminal_interrupt_to_the_process_group_stops_the_supervisor_with_no_traceback() -> None:
    driver, child = _driver()

    os.killpg(driver.pid, signal.SIGINT)
    _, err = driver.communicate(timeout=15)

    assert not _alive(child)
    assert err == ""
