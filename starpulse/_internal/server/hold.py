"""The wait a worker process ends in: `SIGTERM` stops it, `SIGHUP` reloads its config.

A worker `serve` supervises also stops when its stdin pipe from `serve` closes, which `serve` dying by any signal does.
"""

from __future__ import annotations

import os
import signal
import threading
from collections.abc import Callable

#: Set in a supervised child's environment: its stdin is a pipe from `serve`.
SUPERVISED_ENV = "STARPULSE_SUPERVISED"

#: Set to a descriptor number when the process was handed the page's listening socket on it: by `serve` to the Page API
#: child, and by a `serve` that re-executes itself to its next image.
LISTEN_FD_ENV = "STARPULSE_LISTEN_FD"

#: The directory of the page build `serve` checked, handed to the Page API child so both serve the same one.
STATIC_ENV = "STARPULSE_STATIC"


def hold(stop: threading.Event, reload: Callable[[], None]) -> None:  # pragma: no mutate block — process boundary
    """Block until `SIGTERM`, running `reload` for each `SIGHUP`, one at a time."""
    reloads = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: (stop.set(), reloads.set()))
    signal.signal(signal.SIGHUP, lambda *_: reloads.set())
    if os.environ.get(SUPERVISED_ENV):
        threading.Thread(target=_stop_at_eof, args=(stop, reloads), daemon=True).start()
    while True:
        reloads.wait()
        reloads.clear()
        if stop.is_set():
            return
        reload()


def _stop_at_eof(stop: threading.Event, reloads: threading.Event) -> None:  # pragma: no mutate block — process boundary
    # the descriptor, not `sys.stdin.buffer`: a buffered read holds a lock the interpreter cannot take at shutdown
    while os.read(0, 4096):
        pass
    stop.set()
    reloads.set()
