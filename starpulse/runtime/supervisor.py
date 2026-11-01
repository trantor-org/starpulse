"""`serve` as a supervisor: each context runs as a `starpulse worker <context>` child.

A child is started by `spawn` (`starpulse.runtime.zygote.Forker`: a fork of one preloaded process, else
`subprocess`) with a pipe it exits on when `serve` dies, restarted with a growing delay when it exits and stopped with
`serve`. Past its soft memory limit a child is replaced (the new one starts, then the old one stops); past its hard
limit it is killed and restarted. Each run adapter a `[[runs]]` instance configures gets a child of its own, from
`adapter_contexts`, and is limited like the rest.

`starpulse reload` (`starpulse.runtime.control`) calls `Supervisor.reload`: it reads each child's code and config
again from the installed files (`starpulse.runtime.closure`) and replaces only the children something changed
for, as the ADR "StarPulse Supervises Its Own Context Workers" decides.
"""

from __future__ import annotations

import logging
import os
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starpulse.runs.model import opt_in
from starpulse.runtime import launch
from starpulse.runtime.closure import SELF, Reading, ReloadError
from starpulse.runtime.config import Config, MemoryLimit, runs_adapter
from starpulse.runtime.control import Control
from starpulse.runtime.hold import ADOPT_ENV, LISTEN_FD_ENV, READY_FD_ENV, STATIC_ENV, Adopted, supervised_env
from starpulse.runtime.memory import memory_reader

logger = logging.getLogger(__name__)

_HANGUP = getattr(signal, "SIGHUP", None)

#: The `starpulse worker` contexts `serve` supervises, in start order; the adapter workers follow them (`adapter_contexts`).
WORKER_CONTEXTS = ("api", "pulls", "scheduler", "runs", "flow-metrics", "search", "board")

_MB = 1024 * 1024


def adapter_contexts(config: Config) -> list[str]:
    """The opt-in worker of each run adapter a `[[runs]]` instance of `config` names, once each, in config order."""
    workers = [opt_in.worker_of(runs_adapter(instance.type)) for instance in config.runs if instance.type]
    return list(dict.fromkeys(worker for worker in workers if worker))


def worker_commands(config: Config, config_path: Path | None) -> dict[str, list[str]]:
    """The command of each context `serve` supervises (`WORKER_CONTEXTS`), then of each adapter worker `config` names.

    Search has work only with an `embeddings_url`, so a config without one gets no search child.
    """
    tail = ["--config", str(config_path)] if config_path else []
    contexts = [context for context in WORKER_CONTEXTS if context != "search" or config.search.embeddings_url]
    return {
        context: [
            launch.interpreter(),
            "-m",
            "starpulse",
            "worker",
            context,
            *tail,
        ]
        for context in [*contexts, *adapter_contexts(config)]
    }


def spawn_child(
    command: Sequence[str], listening: socket.socket | None = None, ready: int | None = None
) -> subprocess.Popen:
    """Start a child that dies with `serve` (its stdin pipe closes) and sits outside the terminal's process group.

    A `listening` socket is handed to it on the same descriptor number, named by `LISTEN_FD_ENV`; a `ready` descriptor
    (the write end of a pipe), likewise by `READY_FD_ENV`."""
    env = supervised_env()
    if listening is not None:
        env[LISTEN_FD_ENV] = str(listening.fileno())
    if ready is not None:
        env[READY_FD_ENV] = str(ready)
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        env=env,
        start_new_session=True,
        pass_fds=tuple(fd for fd in (listening and listening.fileno(), ready) if fd is not None),
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


class Supervisor:
    """Keeps one child per command running, from `start` until `stop`."""

    def __init__(
        self,
        commands: Mapping[str, Sequence[str]],
        *,
        spawn: Callable[..., Any] = spawn_child,
        sockets: Mapping[str, socket.socket] | None = None,
        first_delay: float = 1.0,
        longest_delay: float = 60.0,
        stable_after: float = 60.0,
        poll: float = 0.5,
        grace: float = 10.0,
        warm: float = 30.0,
        read: Callable[[str], Reading] | None = None,
        baseline: Callable[[str], Reading] | None = None,
        execute: Callable[[], None] = launch.exec_self,
        retire: Callable[[], None] | None = None,
        control: Path | None = None,
        limits: Mapping[str, MemoryLimit] | None = None,
        memory: Callable[[int], int] | None = memory_reader(),
        sample_every: float = 5.0,
        admit: Callable[[], None] | None = None,
        adopted: Mapping[str, Adopted] | None = None,
    ) -> None:
        self._admit = admit
        self._adopted = dict(adopted or {})
        self._children = {name: _Child(command) for name, command in commands.items()}
        self._spawn = spawn
        self._sockets = dict(sockets or {})
        self._first_delay = first_delay
        self._longest_delay = longest_delay
        self._stable_after = stable_after
        self._poll = poll
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
        self._thread: threading.Thread | None = None
        self._read = read
        self._baseline = baseline or read
        self._execute = execute
        self._retire = retire
        self._control = Control(control, self) if control else None
        self._seen: dict[str, Reading] = {}

    def _delay(self, failures: int) -> float:
        return min(self._longest_delay, self._first_delay * 2 ** (failures - 1)) if failures else 0.0

    def tick(self, now: float) -> None:
        """Note each child that exited and start each one that is due, at monotonic time `now`."""
        with self._lock:
            if self._halt.is_set():
                return
            for name, child in self._children.items():
                if child.proc is not None and child.proc.poll() is not None:
                    code = child.proc.poll()
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

    def _launch(self, name: str, child: _Child, now: float, ready: int | None = None) -> None:
        listening = self._sockets.get(name)
        if listening is None:
            child.proc = self._spawn(child.command)
        elif ready is None:
            child.proc = self._spawn(child.command, listening)
        else:
            child.proc = self._spawn(child.command, listening, ready)
        child.started = child.sampled = now
        logger.info("worker %s started as pid %s", name, child.proc.pid)

    def _check_memory(self, name: str, child: _Child, now: float) -> None:
        """Replace `child` past its soft limit and kill it past its hard one; the caller holds the lock."""
        try:
            used = self._memory(child.proc.pid)  # type: ignore[misc]
        except OSError, ValueError, IndexError, subprocess.CalledProcessError:
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
            self._launch(name, child, now)
            self._end([old])

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
        while not self._halt.wait(self._poll):
            self.tick(time.monotonic())

    def _readings(self, read: Callable[[str], Reading] | None = None) -> dict[str, Reading]:
        read = read or self._read
        if read is None:
            raise ReloadError("this supervisor reads no installed code")
        names = [*self._children, SELF]
        with ThreadPoolExecutor(len(names)) as pool:
            return dict(zip(names, pool.map(read, names), strict=True))

    def _admitted(self) -> None:
        if self._admit is None:
            return
        try:
            self._admit()
        except ValueError as exc:
            raise ReloadError(str(exc)) from exc

    def reload(self) -> dict[str, Any]:
        """Replace each child whose code or database changed since the last reading, tell each whose only change is its
        live config block to re-read it, and keep the rest; report each as "replaced", "reloaded" or "kept".

        When `serve`'s own code changed the Page API is replaced first, beside the old one on the shared socket, from the
        release now behind the launcher; every other child is ended and `supervisor` reports "re-executed": the caller
        sends that report, then calls `reexec`, and the next image adopts the Page API. The report's `reads` is
        "launcher" when the code was read from the release behind the launcher, which a caller that probes code through
        its own interpreter (an older `starpulse reload`) lacks, and so cannot trust a "kept". Raises `ReloadError`,
        changing nothing, when a reading fails or `admit` refuses the definitions the config now names."""
        self._admitted()
        after = self._readings()
        with self._lock:
            if self._halt.is_set():
                raise ReloadError("serve is stopping")
            own = self._seen.get(SELF)
            reexec = own is not None and not own.same_code(after[SELF])
            if reexec:
                self._halt.set()
                os.environ.pop(STATIC_ENV, None)  # the next release serves the page build it ships
                for name in self._sockets:
                    self._replace(name, self._children[name])
                self._end([c.proc for n, c in self._children.items() if n not in self._sockets and c.proc is not None])
                outcomes = dict.fromkeys(self._children, "replaced")
            else:
                if self._retire and self._code_changed(after):
                    self._retire()
                outcomes = {n: self._apply(n, c, self._seen.get(n), after[n]) for n, c in self._children.items()}
            self._seen = after
        return {"supervisor": "re-executed" if reexec else "kept", "reads": "launcher", "children": outcomes}

    def _code_changed(self, after: Mapping[str, Reading]) -> bool:
        return any(n not in self._seen or not self._seen[n].same_code(after[n]) for n in self._children)

    def _apply(self, name: str, child: _Child, before: Reading | None, now: Reading) -> str:
        if before is None or not before.same_code(now) or before.restart != now.restart:
            return self._replace(name, child)
        if before.live == now.live:
            return "kept"
        running = child.proc is not None and child.proc.poll() is None
        if running and _HANGUP is None:
            return self._replace(name, child)
        if running:
            child.proc.send_signal(_HANGUP)
        return "reloaded"

    def _replace(self, name: str, child: _Child) -> str:
        old = child.proc
        child.failures = 0
        if old is not None and old.poll() is None and name in self._sockets:
            self._launch_beside(name, child, old)
        else:
            if old is not None:
                self._end([old])
            self._launch(name, child, time.monotonic())
        return "replaced"

    def _launch_beside(self, name: str, child: _Child, old: Any) -> None:
        """Start the new child on the shared socket, wait until it is about to serve (or `warm` seconds, or its exit),
        then end `old`, so the old one keeps answering while the new one starts."""
        read_end, write_end = os.pipe()
        try:
            self._launch(name, child, time.monotonic(), write_end)
            os.close(write_end)
            write_end = -1
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
            if write_end >= 0:
                os.close(write_end)
        self._end([old])

    def reexec(self) -> None:
        """Replace this process with a new one running the same command, after `reload` reported "re-executed".

        The new image adopts the socket it holds (`LISTEN_FD_ENV`), so a connection made meanwhile queues in its backlog,
        and the Page API child that `reload` started beside the old one (`ADOPT_ENV`), which keeps answering meanwhile."""
        if self._control:
            self._control.stop()
        for name, listening in self._sockets.items():  # only the Page API's: one descriptor to name
            listening.set_inheritable(True)
            os.environ[LISTEN_FD_ENV] = str(listening.fileno())
            proc = self._children[name].proc
            fd = None if proc is None or proc.poll() is not None else _stdin_fd(proc)
            if fd is not None:
                os.set_inheritable(fd, True)
                os.environ[ADOPT_ENV] = f"{proc.pid}:{fd}"
        self._execute()

    def _end(self, running: list[Any]) -> None:
        """Terminate each process and kill one still running `grace` seconds after."""
        for proc in running:
            proc.terminate()
        deadline = time.monotonic() + self._grace
        for proc in running:
            try:
                proc.wait(max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def stop(self) -> None:
        """End every child, killing one still running `grace` seconds after it was asked to stop."""
        self._halt.set()
        if self._control:
            self._control.stop()
        with self._lock:
            self._end([c.proc for c in self._children.values() if c.proc is not None])
