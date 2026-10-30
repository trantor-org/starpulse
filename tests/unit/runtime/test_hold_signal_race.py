"""A `SIGTERM` that lands while `hold` is entering its wait still stops the worker.

The handler runs in the main thread between two bytecodes. If it takes a lock the interrupted wait holds, the worker
deadlocks and outlives `serve`, which a `SIGTERM` from the pipe watcher thread hits when `serve` dies as the worker starts.
"""

import subprocess
import sys
from pathlib import Path

STRIKE = """
import os, signal, sys, threading
from starpulse.runtime.hold import hold


def strike(frame, event, arg):
    if event == "call" and frame.f_code.co_name == "_release_save":  # a Condition.wait, still holding its lock
        sys.settrace(None)
        os.kill(os.getpid(), signal.SIGTERM)


threading.Timer(1, os.kill, (os.getpid(), signal.SIGTERM)).start()  # a hold that never waits on a Condition
sys.settrace(strike)
hold(threading.Event(), print)
"""


def test_a_sigterm_landing_as_hold_enters_its_wait_stops_it() -> None:
    done = subprocess.run(
        [sys.executable, "-c", STRIKE], capture_output=True, text=True, timeout=15, cwd=Path(__file__).parents[3]
    )

    assert (done.returncode, done.stderr) == (0, "")
