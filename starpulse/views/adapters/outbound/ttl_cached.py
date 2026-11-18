"""A read held for a while, which the contexts worker shares with the page without loading the page's API."""

import threading
import time
from collections.abc import Callable
from typing import Any


def ttl_cached(
    read: Callable[[], dict[str, Any]], ttl: float, clock: Callable[[], float] = time.monotonic
) -> Callable[[], dict[str, Any]]:
    """`read`, asked at most once in `ttl` seconds; the page that asks while it is stale waits for the fresh read."""
    held: tuple[float, dict[str, Any]] | None = None
    lock = threading.Lock()

    def get() -> dict[str, Any]:
        nonlocal held
        with lock:
            if held is None or clock() - held[0] >= ttl:
                held = (clock(), read())
            return held[1]

    return get
