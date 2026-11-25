"""The one wait a test makes on a condition: `until`, bounded only by the hang guard.

A test that starts a thread, server or subprocess waits on the event it needs through `until`, which
returns as soon as the condition holds. The timeout is a hang guard, not a pace: it is reached only when
the code under test is broken, so it is generous and one constant for every test.
"""

import time
from collections.abc import Callable

HANG_GUARD_S = 30.0
POLL_S = 0.005


def until(condition: Callable[[], object], within: float = HANG_GUARD_S) -> bool:
    """Whether `condition` came true within `within` seconds, checked every `POLL_S` seconds."""
    deadline = time.monotonic() + within
    while not condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_S)
    return True
