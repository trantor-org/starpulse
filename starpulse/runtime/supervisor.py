"""`serve` as a supervisor of `starpulse worker` children: `api` (the page), `contexts` (every background context but one as a thread), `pulls` (the Delivery context and its task actor) and `conformance`.

A child is started by `spawn` (`spawn_child`: a `subprocess`) with a pipe it exits on when `serve` dies, restarted with a growing delay when it exits and stopped with
`serve`. Past its soft memory limit a child is replaced (the Page API starts its replacement beside it; `contexts` and `pulls` start their replacement on standby, which prepares read-only and
takes the writer role and leases only once the old one has ended); past its hard
limit it is killed and restarted. The run adapters a `[[runs]]` instance configures are threads of `contexts`
(`starpulse.runtime.contexts`), named by `adapter_contexts`.

`starpulse reload` (`starpulse.runtime.control`) calls `Supervisor.reload`: it reads each child's code and config
again from the installed files (`starpulse.runtime.closure`) and replaces only the children something changed
for, as the ADR "StarPulse Supervises Its Own Context Workers" decides; `contexts` is replaced on the union of its
contexts' closures and told to re-read the live config blocks of any one of them over `SIGHUP`.
"""

import logging
import os
import select
import selectors
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from starpulse.event_log.process_exit import ExitWatch
from starpulse.runs.model import opt_in
from starpulse.runtime import launch
from starpulse.runtime.closure import SELF, Reading, ReloadError
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

_HANGUP = getattr(signal, "SIGHUP", None)

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
        read: Callable[[str], Reading] | None = None,
        baseline: Callable[[str], Reading] | None = None,
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
        self._read = read
        self._baseline = baseline or read
        self._execute = execute
        self._control = Control(control, self) if control else None
        self._seen: dict[str, Reading] = {}

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
        if self._read:
            try:
                self._seen = self._readings(self._baseline)
            except ReloadError as exc:
                logger.warning("reload: no baseline for the installed code: %s", exc)
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

    def _readings(self, read: Callable[[str], Reading] | None = None) -> dict[str, Reading]:
        read = read or self._read
        if read is None:
            raise ReloadError("this supervisor reads no installed code")
        names = [*self._children, SELF]
        with ThreadPoolExecutor(len(names)) as pool:
            return dict(zip(names, pool.map(read, names), strict=True))

    def reload(self) -> dict[str, Any]:
        """Replace each child whose code or database changed since the last reading, tell each whose only change is its
        live config block to re-read it, and keep the rest; report each as "replaced", "reloaded" or "kept".

        When `serve`'s own code changed the Page API is replaced first, beside the old one on the shared socket, from the
        release now behind the launcher; every other child whose code or config changed is replaced the same way (beside
        the old one where it can run so), and `supervisor` reports "re-executed": the caller sends that report, then
        calls `reexec`, and the next image adopts the Page API and every other child, which stays running across the
        exec, so no child starts cold and no context's ready stamp is dropped. A child whose code and config did not
        change is reported as "kept", the rest as "replaced". The report's `reads` is
        "launcher" when the code was read from the release behind the launcher, which a caller that probes code through
        its own interpreter (an older `starpulse reload`) lacks, and so cannot trust a "kept". Raises `ReloadError`,
        changing nothing, when a reading fails."""
        after = self._readings()
        with self._lock:
            if self._halt.is_set():
                raise ReloadError("serve is stopping")
            own = self._seen.get(SELF)
            reexec = own is not None and not own.same_code(after[SELF])
            if reexec:
                for name in self._sockets:
                    self._replace(name, self._children[name])
                outcomes = {
                    n: self._hand_over(n, c, after[n]) for n, c in self._children.items() if n not in self._sockets
                }
                outcomes.update(dict.fromkeys(self._sockets, "replaced"))
                self._halt.set()  # only once the handover held: `_run` ends on it, and a failed reload must leave it running
            else:
                outcomes = {n: self._apply(n, c, self._seen.get(n), after[n]) for n, c in self._children.items()}
            self._seen = after
        return {"supervisor": "re-executed" if reexec else "kept", "reads": "launcher", "children": outcomes}

    def _apply(self, name: str, child: _Child, before: Reading | None, now: Reading) -> str:
        if before is None or not before.same_code(now) or before.restart != now.restart:
            return self._replace(name, child)
        return self._keep(name, child, before, now)

    def _keep(self, name: str, child: _Child, before: Reading, now: Reading) -> str:
        """Leave a child whose code is unchanged running: "kept", or "reloaded" after a SIGHUP when only its live config
        block changed (replaced where there is no SIGHUP to send)."""
        if before.live == now.live:
            return "kept"
        running = child.proc is not None and child.proc.poll() is None
        if running and _HANGUP is None:
            return self._replace(name, child)
        if running:
            child.proc.send_signal(_HANGUP)
        return "reloaded"

    def _hand_over(self, name: str, child: _Child, now: Reading) -> str:
        """Before a re-exec, keep a running child whose own code and config are unchanged for the next image to adopt
        (`reexec`), and replace any other from the release behind the launcher, beside the old one where it can run
        so, then hand the new one over too: the next image starts no child, so no context's stamp is ever dropped."""
        before = self._seen.get(name)
        alive = child.proc is not None and child.proc.poll() is None
        self._handed.add(name)
        if alive and before is not None and before.same_code(now) and before.restart == now.restart:
            if _stdin_fd(child.proc) is not None:
                return self._keep(name, child, before, now)
        return self._replace(name, child)

    def _replace(self, name: str, child: _Child) -> str:
        old = child.proc
        child.failures = 0
        if old is not None and old.poll() is None and self._beside(name):
            self._launch_beside(name, child, old)
        else:
            if old is not None:
                self._end([old])
            self._launch(name, child, time.monotonic())
        return "replaced"

    def _beside(self, name: str) -> bool:
        return name in self._sockets or name in self._standby

    def _launch_beside(self, name: str, child: _Child, old: Any) -> None:
        """Start the new child beside `old`, wait until it is about to serve (or `warm` seconds, or its exit), then end
        `old`, so the old one keeps answering while the new one starts.

        A standby child (`standby`) is handed a go pipe too and prepares read-only until `serve` closes it, which it does
        once `old` has ended: its writer and leases are never held beside the old one's.

        Raises `ReloadError`, keeping `old` as the child, when the new one exited before it was serving."""
        read_end, write_end = os.pipe()
        go_read, go_write = os.pipe() if name in self._standby else (None, None)
        before = (child.started, child.sampled, child.launches)
        try:
            self._launch(name, child, time.monotonic(), write_end, go_read)
            os.close(write_end)
            write_end = -1
            if go_read is not None:
                os.close(go_read)
                go_read = None
            deadline = time.monotonic() + self._warm
            serving = select.poll()
            serving.register(read_end, select.POLLIN)
            while child.proc.poll() is None and not serving.poll(100):
                if time.monotonic() >= deadline:
                    logger.warning(
                        "worker %s pid %s was not serving after %.0fs; ending the old one",
                        name,
                        child.proc.pid,
                        self._warm,
                    )
                    break
        finally:
            os.close(read_end)
            for fd in (write_end, go_read):
                if fd is not None and fd >= 0:
                    os.close(fd)
        try:
            if (code := child.proc.poll()) is not None:
                logger.error("worker %s replacement exited with %s before it was serving; keeping the old one", name, code)
                child.proc, (child.started, child.sampled, child.launches) = old, before
                raise ReloadError(f"{name}: the replacement exited with {code} before it was serving")
            self._end([old])
        finally:
            if go_write is not None:
                os.close(go_write)

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
        deadline = time.monotonic() + self._grace
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
