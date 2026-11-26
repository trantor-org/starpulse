"""`serve` as a supervisor of `starpulse worker` children: `api` (the page), `contexts` (every background context but one as a thread), `pulls` (the Delivery context and its task actor) and `conformance`.

A child is started by `spawn` (`spawn_child`: a `subprocess`) with a pipe it exits on when `serve` dies, restarted with a growing delay when it exits and stopped with
`serve`. Past its soft memory limit a child is replaced (the Page API starts its replacement beside it; `contexts` and `pulls` start their replacement on standby, which prepares read-only and
takes the writer role and leases only once the old one has ended); past its hard
limit it is killed and restarted. The run adapters a `[[runs]]` instance configures are threads of `contexts`
(`starpulse.runtime.contexts`), named by `adapter_contexts`.

`starpulse reload` (`starpulse.runtime.control`) calls `Supervisor.reload`: it replaces every child together from the
installed code and re-executes `serve`, as the ADR "StarPulse Supervises Its Own Context Workers" decides, reading and
hashing no code to choose which.
"""

import logging
import os
import select
import selectors
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from starpulse.event_log.process_exit import ExitWatch
from starpulse.runs.model import opt_in
from starpulse.runtime import launch
from starpulse.runtime.closure import ReloadError
from starpulse.runtime.config import Config, MemoryLimit, rehearsing, runs_adapter
from starpulse.runtime.control import Control
from starpulse.runtime.hold import (
    ADOPT_ENV,
    GO_FD_ENV,
    LISTEN_FD_ENV,
    READY_FD_ENV,
    Adopted,
    supervised_env,
)
from starpulse.runtime.memory import memory_reader

logger = logging.getLogger(__name__)


#: The `starpulse worker` children `serve` supervises, in start order.
WORKER_CONTEXTS = ("api", "contexts", "pulls", "conformance")

_MB = 1024 * 1024

#: Seconds `_run` sleeps at most when a child's exit cannot be watched, so `tick` still polls it.
_WATCH_RETRY = 1.0


def adapter_contexts(config: Config) -> list[str]:
    """The opt-in worker of each run adapter a `[[runs]]` instance of `config` names, once each, in config order."""
    workers = [opt_in.worker_of(runs_adapter(instance.type)) for instance in config.runs if instance.type]
    return list(dict.fromkeys(worker for worker in workers if worker))


def worker_commands(config_path: Path | None) -> dict[str, list[str]]:
    """The command of each child `serve` supervises (`WORKER_CONTEXTS`): the Page API, the one `contexts` process,
    which runs the contexts the config names (`starpulse.runtime.contexts.contexts_of`), the `pulls` process, which runs
    the Delivery context and its task actor alone so no other context's threads share its GIL, and the `conformance`
    process, which runs the monitor alone so its replay holds no GIL the contexts share. A rehearsal has no `pulls`."""
    tail = ["--config", str(config_path)] if config_path else []
    return {
        context: [launch.interpreter(), "-m", "starpulse", "worker", context, *tail]
        for context in WORKER_CONTEXTS
        if not (context == "pulls" and rehearsing())  # a rehearsal's task actor would move tasks of the live board
    }


def spawn_child(
    command: Sequence[str],
    listening: socket.socket | None = None,
    ready: int | None = None,
    go: int | None = None,
    held: Mapping[str, socket.socket] | None = None,
) -> subprocess.Popen:
    """Start a child that dies with `serve` (its stdin pipe closes) and sits outside the terminal's process group.

    A `listening` socket is handed to it on the same descriptor number, named by `LISTEN_FD_ENV`; a `ready` descriptor
    (the write end of a pipe), likewise by `READY_FD_ENV`, and a `go` descriptor (the read end of a pipe `serve` closes the
    other end of when the child may take over from its predecessor), by `GO_FD_ENV`; each `held` socket likewise by the
    variable it is keyed by."""
    env = supervised_env()
    if listening is not None:
        env[LISTEN_FD_ENV] = str(listening.fileno())
    if ready is not None:
        env[READY_FD_ENV] = str(ready)
    if go is not None:
        env[GO_FD_ENV] = str(go)
    for env_name, kept in (held or {}).items():
        env[env_name] = str(kept.fileno())
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        env=env,
        start_new_session=True,
        pass_fds=tuple(
            fd for fd in (listening and listening.fileno(), ready, go, *(k.fileno() for k in (held or {}).values()))
            if fd is not None
        ),
    )


def _stdin_fd(proc: Any) -> int | None:
    """The descriptor of the stdin pipe `proc` exits on, which `serve` holds the write end of."""
    if isinstance(proc, Adopted):
        return proc.fd
    stdin = getattr(proc, "stdin", None)
    return None if stdin is None else stdin.fileno()


@dataclass
class _Child:
    command: Sequence[str]
    proc: Any = None
    started: float = 0.0
    failures: int = 0
    due: float = 0.0
    sampled: float = float("-inf")
    launches: int = 0


@dataclass
class _Beside:
    """A replacement started beside `old`: its readiness pipe's read end and, for a standby child, its go pipe's write end."""

    name: str
    child: _Child
    old: Any
    before: tuple[float, float, int]
    ready: int
    go: int | None
    deadline: float


class Supervisor:
    """Keeps one child per command running, from `start` until `stop`."""

    def __init__(
        self,
        commands: Mapping[str, Sequence[str]],
        *,
        spawn: Callable[..., Any] = spawn_child,
        sockets: Mapping[str, socket.socket] | None = None,
        held: Mapping[str, Mapping[str, socket.socket]] | None = None,
        first_delay: float = 1.0,
        longest_delay: float = 60.0,
        stable_after: float = 60.0,
        grace: float = 10.0,
        warm: float = 30.0,
        execute: Callable[[], None] = launch.exec_self,
        control: Path | None = None,
        limits: Mapping[str, MemoryLimit] | None = None,
        memory: Callable[[int], int] | None = memory_reader(),
        sample_every: float = 5.0,
        adopted: Mapping[str, Adopted] | None = None,
        refuse: Callable[[str], None] | None = None,
        standby: Collection[str] = (),
    ) -> None:
        self._standby = frozenset(standby)
        self._refuse = refuse
        self._refused = False
        self._adopted = dict(adopted or {})
        self._handed: set[str] = set()
        self._children = {name: _Child(command) for name, command in commands.items()}
        self._spawn = spawn
        self._sockets = dict(sockets or {})
        self._held = dict(held or {})
        self._first_delay = first_delay
        self._longest_delay = longest_delay
        self._stable_after = stable_after
        self._grace = grace
        self._warm = warm
        self._limits = dict(limits or {})
        self._memory = memory
        self._sample_every = sample_every
        if self._limits and memory is None:
            logger.warning("no memory reader on %s; worker memory limits are not enforced", sys.platform)
            self._limits = {}
        self._lock = threading.Lock()
        self._halt = threading.Event()
        self._wake_read, self._wake_write = socket.socketpair()
        self._wake_read.setblocking(False)
        self._wake_write.setblocking(False)
        self._thread: threading.Thread | None = None
        self._execute = execute
        self._control = Control(control, self) if control else None

    def _delay(self, failures: int) -> float:
        return min(self._longest_delay, self._first_delay * 2 ** (failures - 1)) if failures else 0.0

    def tick(self, now: float) -> None:
        """Note each child that exited and start each one that is due, at monotonic time `now`."""
        with self._lock:
            if self._halt.is_set() or self._refused:
                return
            for name, child in self._children.items():
                if child.proc is not None and child.proc.poll() is not None:
                    code = child.proc.poll()
                    if code == os.EX_CONFIG and child.launches == 1 and self._refuse is not None:
                        self._refused = True  # the first run exited on the config: a restart would only exit on it again
                        self._refuse(name)
                        return
                    ran = now - child.started
                    child.failures = 0 if ran >= self._stable_after else child.failures + 1
                    child.due = now + self._delay(child.failures)
                    child.proc = None
                    logger.warning(
                        "worker %s exited with %s after %.1fs; restarting at +%.1fs", name, code, ran, child.due - now
                    )
                if child.proc is None and now >= child.due:
                    self._launch(name, child, now)
                elif child.proc is not None and name in self._limits and now - child.sampled >= self._sample_every:
                    child.sampled = now
                    self._check_memory(name, child, now)

    def _launch(self, name: str, child: _Child, now: float, ready: int | None = None, go: int | None = None) -> None:
        listening = self._sockets.get(name)
        handshake = {key: fd for key, fd in (("ready", ready), ("go", go)) if fd is not None}
        if name in self._held:
            handshake["held"] = self._held[name]
        child.proc = self._spawn(child.command, *([] if listening is None else [listening]), **handshake)
        child.started = child.sampled = now
        child.launches += 1
        logger.info("worker %s started as pid %s", name, child.proc.pid)
        self._nudge()

    def _check_memory(self, name: str, child: _Child, now: float) -> None:
        """Replace `child` past its soft limit and kill it past its hard one; the caller holds the lock."""
        try:
            used = self._memory(child.proc.pid)  # type: ignore[misc]
        except psutil.Error:  # the child is gone or unreadable; the next tick reaps or retries it
            return
        limit = self._limits[name]
        old = child.proc
        if used >= limit.hard_mb * _MB:
            logger.warning(
                "worker %s pid %s at %d MB passed its hard limit of %d MB; killing it",
                name,
                old.pid,
                used // _MB,
                limit.hard_mb,
            )
            old.kill()
            old.wait()
            self._launch(name, child, now)
        elif used >= limit.soft_mb * _MB:
            logger.warning(
                "worker %s pid %s at %d MB passed its soft limit of %d MB; replacing it",
                name,
                old.pid,
                used // _MB,
                limit.soft_mb,
            )
            if self._beside(name):  # the old one runs until the new one is about to serve or take over
                try:
                    self._launch_beside(name, child, old)
                except ReloadError as exc:  # the old one is kept; the next sample past the limit tries again
                    logger.warning("worker %s not replaced: %s", name, exc)
            else:  # a worker holds ports and leases the next one needs: it starts once the old one has freed them
                self._end([old])
                self._launch(name, child, now)

    def start(self) -> None:
        """Start every child and keep them running on a background thread until `stop`."""
        now = time.monotonic()
        for name, proc in self._adopted.items():  # the previous image's child, kept in place of one started now
            child = self._children.get(name)
            if child is None:
                proc.terminate()
            else:
                child.proc, child.started, child.sampled = proc, now, now
        self.tick(now)
        self._thread = threading.Thread(target=self._run, name="worker-supervisor", daemon=True)
        self._thread.start()
        if self._control:
            self._control.start()

    def _run(self) -> None:
        """Sleep on each child's exit and on `_nudge`, and wake only for one, or for a restart or memory sample due."""
        while not self._halt.is_set():
            watches: list[ExitWatch] = []
            with self._lock:
                timeout = self._next_deadline(time.monotonic())
                try:
                    for child in self._children.values():
                        if child.proc is not None:
                            watches.append(ExitWatch(child.proc.pid))
                except OSError as error:
                    logger.warning("cannot watch a child's exit, polling instead: %s", error)
                    timeout = _WATCH_RETRY if timeout is None else min(timeout, _WATCH_RETRY)
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(self._wake_read, selectors.EVENT_READ)
                    for watch in watches:
                        selector.register(watch.fileno(), selectors.EVENT_READ)
                    selector.select(timeout)
            finally:
                for watch in watches:
                    watch.close()
            self._drain()
            self.tick(time.monotonic())

    def _next_deadline(self, now: float) -> float | None:
        """Seconds until the next restart or memory sample is due, or None while nothing is: the caller holds the lock."""
        due = [c.due for c in self._children.values() if c.proc is None]
        due += [c.sampled + self._sample_every for n, c in self._children.items() if c.proc is not None and n in self._limits]
        return max(0.0, min(due) - now) if due else None

    def _nudge(self) -> None:
        """Wake `_run` to watch the children as they are now."""
        try:
            self._wake_write.send(b"x")
        except OSError:  # full, which wakes it anyway, or closed
            pass

    def _drain(self) -> None:
        try:
            while self._wake_read.recv(4096):
                pass
        except OSError:  # nothing more to read
            pass

    def reload(self) -> dict[str, Any]:
        """Replace every child together from the release now behind the launcher and report "re-executed", with the
        `seconds` it took: the caller sends that report, then calls `reexec`, and the next image adopts every
        replacement, which stays running across the exec, so no child starts cold and no context's ready stamp is
        dropped.

        Each child that can run beside its old one (the Page API, and a standby one) is started beside it, all before
        any is waited on; each old one ends once its replacement is serving. Raises `ReloadError` when a replacement
        exited before serving, its old child kept; `serve` keeps supervising on any raise."""
        started = time.monotonic()
        with self._lock:
            if self._halt.is_set():
                raise ReloadError("serve is stopping")
            self._replace_all()
            self._handed.update(self._children)
            self._halt.set()  # only once every replacement held: `_run` ends on it, and a failed reload must leave it running
        seconds = round(time.monotonic() - started, 1)
        logger.info("reload: replaced %d children in %.1fs", len(self._children), seconds)
        return {
            "supervisor": "re-executed",
            "reads": "launcher",
            "seconds": seconds,
            "children": dict.fromkeys(self._children, "replaced"),
        }

    def _replace_all(self) -> None:
        beside: list[_Beside] = []
        try:
            for name, child in self._children.items():
                child.failures = 0
                if child.proc is not None and child.proc.poll() is None and self._beside(name):
                    beside.append(self._start_beside(name, child, child.proc))
            for name, child in self._children.items():
                if not any(pending.child is child for pending in beside):
                    if child.proc is not None:
                        self._end([child.proc])
                    self._launch(name, child, time.monotonic())
        except BaseException:
            for pending in beside:
                self._abandon(pending)
            raise
        self._finish_beside(beside)

    def _beside(self, name: str) -> bool:
        return name in self._sockets or name in self._standby

    def _launch_beside(self, name: str, child: _Child, old: Any) -> None:
        self._finish_beside([self._start_beside(name, child, old)])

    def _start_beside(self, name: str, child: _Child, old: Any) -> _Beside:
        """Start the new child beside `old`, with a readiness pipe that reports when it is about to serve.

        A standby child (`standby`) is handed a go pipe too and prepares read-only until `serve` closes it, which it does
        once `old` has ended: its writer and leases are never held beside the old one's."""
        read_end, write_end = os.pipe()
        go_read, go_write = os.pipe() if name in self._standby else (None, None)
        before = (child.started, child.sampled, child.launches)
        try:
            self._launch(name, child, time.monotonic(), write_end, go_read)
        except BaseException:
            os.close(read_end)
            if go_write is not None:
                os.close(go_write)
            raise
        finally:
            os.close(write_end)
            if go_read is not None:
                os.close(go_read)
        return _Beside(name, child, old, before, read_end, go_write, time.monotonic() + self._warm)

    def _abandon(self, pending: _Beside) -> None:
        """Drop a replacement that never took over: end it, and keep the old child as the child."""
        if pending.child.proc is not pending.old:
            self._end([pending.child.proc])
            pending.child.proc, (pending.child.started, pending.child.sampled, pending.child.launches) = (
                pending.old,
                pending.before,
            )
        self._close(pending)

    @staticmethod
    def _close(pending: _Beside) -> None:
        os.close(pending.ready)
        if pending.go is not None:
            os.close(pending.go)

    def _finish_beside(self, pending: list[_Beside]) -> None:
        """Wait until each replacement is about to serve (or `warm` seconds after it started, or its exit), ending its old
        child as it is, so the old ones keep answering while the new ones start together.

        Raises `ReloadError`, keeping the old child as the child of each replacement that exited before it was serving,
        after every other old child has ended."""
        waiting = {p.ready: p for p in pending}
        serving = select.poll()
        for p in pending:
            serving.register(p.ready, select.POLLIN)
        ended: list[tuple[_Beside, float]] = []
        failures: list[str] = []
        try:
            while waiting:
                for fd, _ in serving.poll(100):
                    self._ready(waiting.pop(fd), serving, ended, failures)
                for p in [p for p in waiting.values() if p.child.proc.poll() is not None or time.monotonic() >= p.deadline]:
                    if p.child.proc.poll() is None:
                        logger.warning(
                            "worker %s pid %s was not serving after %.0fs; ending the old one",
                            p.name,
                            p.child.proc.pid,
                            self._warm,
                        )
                    del waiting[p.ready]
                    self._ready(p, serving, ended, failures)
        finally:
            for p in waiting.values():
                self._abandon(p)
            for p, deadline in ended:
                try:
                    self._reap([p.old], deadline)
                finally:
                    self._close(p)
        if failures:
            raise ReloadError("; ".join(failures))

    def _ready(self, p: _Beside, serving: Any, ended: list[tuple[_Beside, float]], failures: list[str]) -> None:
        serving.unregister(p.ready)
        if (code := p.child.proc.poll()) is not None:
            logger.error("worker %s replacement exited with %s before it was serving; keeping the old one", p.name, code)
            failures.append(f"{p.name}: the replacement exited with {code} before it was serving")
            p.child.proc, (p.child.started, p.child.sampled, p.child.launches) = p.old, p.before
            self._close(p)
            return
        p.old.terminate()
        ended.append((p, time.monotonic() + self._grace))

    def reexec(self) -> None:
        """Replace this process with a new one running the same command, after `reload` reported "re-executed".

        The new image adopts the socket it holds (`LISTEN_FD_ENV`), so a connection made meanwhile queues in its backlog,
        and the Page API child that `reload` started beside the old one (`ADOPT_ENV`), which keeps answering meanwhile."""
        if self._control:
            self._control.stop()
        handed = []
        for name, listening in self._sockets.items():  # only the Page API's: one descriptor to name
            listening.set_inheritable(True)
            os.environ[LISTEN_FD_ENV] = str(listening.fileno())
            handed.append(name)
        for held in self._held.values():  # the `contexts` child's: it is replaced, never started beside the old one
            for env_name, listening in held.items():
                listening.set_inheritable(True)
                os.environ[env_name] = str(listening.fileno())
        handed.extend(sorted(self._handed))
        parts = []
        for name in handed:
            proc = self._children[name].proc
            fd = None if proc is None or proc.poll() is not None else _stdin_fd(proc)
            if fd is not None:
                os.set_inheritable(fd, True)
                parts.append(f"{name}={proc.pid}:{fd}")
        if parts:
            os.environ[ADOPT_ENV] = ",".join(parts)
        self._execute()

    def _end(self, running: list[Any]) -> None:
        """Terminate each process and kill one still running `grace` seconds after."""
        for proc in running:
            proc.terminate()
        self._reap(running, time.monotonic() + self._grace)

    @staticmethod
    def _reap(running: list[Any], deadline: float) -> None:
        for proc in running:
            try:
                # adr-exempt: handshake
                proc.wait(max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def stop(self) -> None:
        """End every child, killing one still running `grace` seconds after it was asked to stop."""
        self._halt.set()
        self._nudge()
        if self._control:
            self._control.stop()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join()
        with self._lock:
            self._end([c.proc for c in self._children.values() if c.proc is not None])
        self._wake_read.close()
        self._wake_write.close()
