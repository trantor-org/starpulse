"""`serve` as a supervisor: each context whose `*_worker` setting is false runs as a `starpulse worker <context>` child.

A child is started with `subprocess` on a pipe it exits on when `serve` dies, restarted with a growing delay when it exits and stopped with `serve`. Past its
soft memory limit a child is replaced (the new one starts, then the old one stops); past its hard limit it is killed and
restarted. A context
whose setting is true is run by something outside `serve`, so it gets no child here.

`starpulse reload` (`starpulse._internal.server.control`) calls `Supervisor.reload`: it reads each child's code and config
again from the installed files (`starpulse._internal.server.closure`) and replaces only the children something changed
for, as the ADR "StarPulse Supervises Its Own Context Workers" decides.
"""

from __future__ import annotations

import logging
import os
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

from starpulse._internal.config.config import Config, MemoryLimit
from starpulse._internal.server.closure import SELF, Reading, ReloadError
from starpulse._internal.server.control import Control
from starpulse._internal.server.hold import LISTEN_FD_ENV, SUPERVISED_ENV
from starpulse._internal.server.rss import rss_reader

logger = logging.getLogger(__name__)

_HANGUP = getattr(signal, "SIGHUP", None)

#: The `starpulse worker` contexts, by the `Config` flag that says an outside runner owns them.
WORKER_FLAGS = {
    "api": "api_worker",
    "pulls": "delivery_worker",
    "autopilot": "autopilot_worker",
    "runs": "runs_worker",
    "forwarding": "forwarding_worker",
    "history": "history_worker",
    "search": "search_worker",
    "board": "board_worker",
}

#: The contexts that read the Board: a hub has no Board child for them to read it from.
READERS = ("pulls", "runs", "autopilot")

_MB = 1024 * 1024


def worker_commands(config: Config, config_path: Path | None, *, hub: bool = False) -> dict[str, list[str]]:
    """The command of each context `serve` supervises: the ones whose `*_worker` setting is false.

    A hub serves its page in-process, so it gets no Page API child.

    Forwarding has work only with a `[forward]` table, so a config without one gets no forwarding child. A hub keeps its
    history threads in-process, so it gets no history child. Search has work only with an `embeddings_url`, and a hub keeps
    no search index, so a config without one, or a hub, gets no search child. A hub keeps its board writers in-process, so it
    gets no board child, and its pulls, runs and autopilot workers start the board adapter themselves
    (`--local-board`) where the others read the replica the Board child publishes.
    """
    tail = ["--config", str(config_path)] if config_path else []
    return {
        context: [
            sys.executable,
            "-m",
            "starpulse",
            "worker",
            context,
            *tail,
            *(["--local-board"] if hub and context in READERS else []),
        ]
        for context, flag in WORKER_FLAGS.items()
        if not getattr(config, flag)
        and (context != "forwarding" or config.forward is not None)
        and (context != "history" or not hub)
        and (context != "search" or (config.search.embeddings_url and not hub))
        and (context != "board" or not hub)
        and (context != "api" or not hub)
    }


def spawn_child(command: Sequence[str], listening: socket.socket | None = None) -> subprocess.Popen:
    """Start a child that dies with `serve` (its stdin pipe closes) and sits outside the terminal's process group.

    A `listening` socket is handed to it on the same descriptor number, named by `LISTEN_FD_ENV`."""
    env = {**os.environ, SUPERVISED_ENV: "1"}
    if listening is not None:
        env[LISTEN_FD_ENV] = str(listening.fileno())
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        env=env,
        start_new_session=True,
        pass_fds=() if listening is None else (listening.fileno(),),
    )


def _exec_self() -> None:  # pragma: no mutate block — process boundary
    os.execv(sys.executable, sys.orig_argv)


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
        read: Callable[[str], Reading] | None = None,
        execute: Callable[[], None] = _exec_self,
        control: Path | None = None,
        limits: Mapping[str, MemoryLimit] | None = None,
        rss: Callable[[int], int] | None = rss_reader(),
        sample_every: float = 5.0,
    ) -> None:
        self._children = {name: _Child(command) for name, command in commands.items()}
        self._spawn = spawn
        self._sockets = dict(sockets or {})
        self._first_delay = first_delay
        self._longest_delay = longest_delay
        self._stable_after = stable_after
        self._poll = poll
        self._grace = grace
        self._limits = dict(limits or {})
        self._rss = rss
        self._sample_every = sample_every
        if self._limits and rss is None:
            logger.warning("no resident-size reader on %s; worker memory limits are not enforced", sys.platform)
            self._limits = {}
        self._lock = threading.Lock()
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self._read = read
        self._execute = execute
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
                elif name in self._limits and now - child.sampled >= self._sample_every:
                    child.sampled = now
                    self._check_memory(name, child, now)

    def _launch(self, name: str, child: _Child, now: float) -> None:
        listening = self._sockets.get(name)
        child.proc = self._spawn(child.command) if listening is None else self._spawn(child.command, listening)
        child.started = child.sampled = now
        logger.info("worker %s started as pid %s", name, child.proc.pid)

    def _check_memory(self, name: str, child: _Child, now: float) -> None:
        """Replace `child` past its soft limit and kill it past its hard one; the caller holds the lock."""
        try:
            used = self._rss(child.proc.pid)  # type: ignore[misc]
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

    def pids(self) -> dict[str, int]:
        """The pid of each child running now."""
        with self._lock:
            return {n: c.proc.pid for n, c in self._children.items() if c.proc is not None and c.proc.poll() is None}

    def start(self) -> None:
        """Start every child and keep them running on a background thread until `stop`."""
        if self._read:
            try:
                self._seen = self._readings()
            except ReloadError as exc:
                logger.warning("reload: no baseline for the installed code: %s", exc)
        self.tick(time.monotonic())
        self._thread = threading.Thread(target=self._run, name="worker-supervisor", daemon=True)
        self._thread.start()
        if self._control:
            self._control.start()

    def _run(self) -> None:
        while not self._halt.wait(self._poll):
            self.tick(time.monotonic())

    def _readings(self) -> dict[str, Reading]:
        if self._read is None:
            raise ReloadError("this supervisor reads no installed code")
        names = [*self._children, SELF]
        with ThreadPoolExecutor(len(names)) as pool:
            return dict(zip(names, pool.map(self._read, names), strict=True))

    def reload(self) -> dict[str, Any]:
        """Replace each child whose code or database changed since the last reading, tell each whose only change is its
        live config block to re-read it, and keep the rest; report each as "replaced", "reloaded" or "kept".

        When `serve`'s own code changed every child is ended and `supervisor` reports "re-executed": the caller
        sends that report, then calls `reexec`. Raises `ReloadError`, changing nothing, when a reading fails."""
        after = self._readings()
        with self._lock:
            if self._halt.is_set():
                raise ReloadError("serve is stopping")
            own = self._seen.get(SELF)
            reexec = own is not None and own.code != after[SELF].code
            if reexec:
                self._halt.set()
                self._end([c.proc for c in self._children.values() if c.proc is not None])
                outcomes = dict.fromkeys(self._children, "replaced")
            else:
                outcomes = {n: self._apply(n, c, self._seen.get(n), after[n]) for n, c in self._children.items()}
            self._seen = after
        return {"supervisor": "re-executed" if reexec else "kept", "children": outcomes}

    def _apply(self, name: str, child: _Child, before: Reading | None, now: Reading) -> str:
        if before is None or (before.code, before.restart) != (now.code, now.restart):
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
        if child.proc is not None:
            self._end([child.proc])
        child.failures = 0
        self._launch(name, child, time.monotonic())
        return "replaced"

    def reexec(self) -> None:
        """Replace this process with a new one running the same command, after `reload` reported "re-executed".

        The new image adopts the socket it holds (`LISTEN_FD_ENV`), so a connection made meanwhile queues in its backlog."""
        if self._control:
            self._control.stop()
        for listening in self._sockets.values():  # only the Page API's: one descriptor to name
            listening.set_inheritable(True)
            os.environ[LISTEN_FD_ENV] = str(listening.fileno())
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
