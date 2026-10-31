"""The wait a worker process ends in: `SIGTERM` stops it, `SIGHUP` reloads its config.

A worker `serve` supervises also stops when its stdin pipe from `serve` closes, which `serve` dying by any signal does.
`watch_supervisor` starts that watch as the process starts, so a worker still starting when `serve` dies ends too.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, MutableMapping

#: Set in a supervised child's environment: its stdin is a pipe from `serve`.
SUPERVISED_ENV = "STARPULSE_SUPERVISED"

#: Freed pages stay resident on the free-threaded build until mimalloc's purge delay lapses; `0` returns them at once.
PURGE_DELAY_ENV = "MIMALLOC_PURGE_DELAY"


def supervised_env() -> dict[str, str]:
    """The environment of a process `serve` supervises: `serve`'s own, marked supervised, with an immediate mimalloc
    purge unless the operator's environment already names a delay."""
    return {PURGE_DELAY_ENV: "0", **os.environ, SUPERVISED_ENV: "1"}


#: Set to a descriptor number when the process was handed the page's listening socket on it: by `serve` to the Page API
#: child, and by a `serve` that re-executes itself to its next image.
LISTEN_FD_ENV = "STARPULSE_LISTEN_FD"

#: Set to a descriptor number in the Page API child a replacing `serve` starts beside the old one: the child writes a byte
#: to it when it is about to serve, and `serve` ends the old child on that byte (`announce_ready`).
READY_FD_ENV = "STARPULSE_READY_FD"

#: Set to `<pid>:<descriptor>` by a `serve` that re-executes: the Page API child it started beside the old one, and the
#: write end of that child's stdin pipe. The next image adopts the child in place of starting its own (`adopted_from_env`).
ADOPT_ENV = "STARPULSE_ADOPT"

#: The directory of the page build `serve` checked, handed to the Page API child so both serve the same one.
STATIC_ENV = "STARPULSE_STATIC"

_watching = False


class Adopted:
    """A child of this process that an earlier image of `serve` started, shaped like the `Popen` the `Supervisor` drives.

    A re-executed process keeps its pid and so its children: the child is waited for by pid, and `fd` is the write end of
    the stdin pipe it exits on, which stays open across the exec."""

    def __init__(self, pid: int, fd: int) -> None:
        self.pid = pid
        self.fd = fd
        self.returncode: int | None = None

    def poll(self) -> int | None:
        if self.returncode is None:
            try:
                done, status = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:  # reaped elsewhere
                done, status = self.pid, 0
            if done:
                self.returncode = os.waitstatus_to_exitcode(status)
                self._close()
        return self.returncode

    def _close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def send_signal(self, number: int) -> None:
        try:
            os.kill(self.pid, number)
        except ProcessLookupError:
            pass

    def terminate(self) -> None:
        self.send_signal(signal.SIGTERM)

    def kill(self) -> None:
        self.send_signal(signal.SIGKILL)

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while (code := self.poll()) is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(str(self.pid), timeout)
            time.sleep(0.05)
        return code


def adopted_from_env(environ: MutableMapping[str, str]) -> Adopted | None:
    """The Page API child the previous image handed over (`ADOPT_ENV`), consuming the variable; None when it named none."""
    handed = environ.pop(ADOPT_ENV, None)
    try:
        pid, fd = (int(part) for part in (handed or "").split(":"))
    except ValueError:
        return None
    return Adopted(pid, fd)


def announce_ready(environ: MutableMapping[str, str]) -> None:
    """Tell the supervisor this child is about to serve, when it asked to be told; a closed pipe is no reason to stop."""
    fd = environ.pop(READY_FD_ENV, None)
    if fd is None:
        return
    try:
        os.write(int(fd), b"1")
        os.close(int(fd))
    except OSError, ValueError:
        pass


def watch_supervisor() -> None:  # pragma: no mutate block — process boundary
    """End this process with `SIGTERM` when its stdin pipe from `serve` closes; a no-op outside a supervised child.

    Called as the process starts: until `hold` installs its handler `SIGTERM` ends the process, and after it `stop` is set.
    """
    global _watching  # once per process: two readers of the pipe would split its bytes
    if os.environ.get(SUPERVISED_ENV) and not _watching:
        _watching = True
        threading.Thread(target=_term_at_eof, daemon=True).start()


def hold(stop: threading.Event, reload: Callable[[], None]) -> None:  # pragma: no mutate block — process boundary
    """Block until `SIGTERM`, running `reload` for each `SIGHUP`, one at a time.

    The wait is a read of the signal wakeup pipe, not an `Event`: a handler runs between two bytecodes of the main
    thread, and `Event.set` takes a lock that a wait interrupted there still holds."""
    woken, wake = os.pipe()
    os.set_blocking(wake, False)
    signal.set_wakeup_fd(wake)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGHUP, lambda *_: None)
    try:
        watch_supervisor()
        while True:
            os.read(woken, 4096)
            if stop.is_set():
                return
            reload()
    finally:
        signal.set_wakeup_fd(-1)
        os.close(woken)
        os.close(wake)


def _term_at_eof() -> None:  # pragma: no mutate block — process boundary
    # the descriptor, not `sys.stdin.buffer`: a buffered read holds a lock the interpreter cannot take at shutdown
    while os.read(0, 4096):
        pass
    os.kill(os.getpid(), signal.SIGTERM)
