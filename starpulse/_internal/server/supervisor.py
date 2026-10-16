"""`serve` as a supervisor: each context whose `*_worker` setting is false runs as a `starpulse worker <context>` child.

A child is started with `subprocess` on a pipe it exits on when `serve` dies, restarted with a growing delay when it exits and stopped with `serve`. A context
whose setting is true is run by something outside `serve`, so it gets no child here.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starpulse._internal.config.config import Config
from starpulse._internal.server.hold import SUPERVISED_ENV

logger = logging.getLogger(__name__)


#: The `starpulse worker` contexts, by the `Config` flag that says an outside runner owns them.
WORKER_FLAGS = {"pulls": "delivery_worker", "autopilot": "autopilot_worker", "runs": "runs_worker"}


def worker_commands(config: Config, config_path: Path | None) -> dict[str, list[str]]:
    """The command of each context `serve` supervises: the ones whose `*_worker` setting is false."""
    tail = ["--config", str(config_path)] if config_path else []
    return {
        context: [sys.executable, "-m", "starpulse", "worker", context, *tail]
        for context, flag in WORKER_FLAGS.items()
        if not getattr(config, flag)
    }


def spawn_child(command: Sequence[str]) -> subprocess.Popen:
    """Start a child that dies with `serve` (its stdin pipe closes) and sits outside the terminal's process group."""
    return subprocess.Popen(
        command, stdin=subprocess.PIPE, env={**os.environ, SUPERVISED_ENV: "1"}, start_new_session=True
    )


@dataclass
class _Child:
    command: Sequence[str]
    proc: Any = None
    started: float = 0.0
    failures: int = 0
    due: float = 0.0


class Supervisor:
    """Keeps one child per command running, from `start` until `stop`."""

    def __init__(
        self,
        commands: Mapping[str, Sequence[str]],
        *,
        spawn: Callable[[Sequence[str]], Any] = spawn_child,
        first_delay: float = 1.0,
        longest_delay: float = 60.0,
        stable_after: float = 60.0,
        poll: float = 0.5,
        grace: float = 10.0,
    ) -> None:
        self._children = {name: _Child(command) for name, command in commands.items()}
        self._spawn = spawn
        self._first_delay = first_delay
        self._longest_delay = longest_delay
        self._stable_after = stable_after
        self._poll = poll
        self._grace = grace
        self._lock = threading.Lock()
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None

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
                    child.proc = self._spawn(child.command)
                    child.started = now
                    logger.info("worker %s started as pid %s", name, child.proc.pid)

    def pids(self) -> dict[str, int]:
        """The pid of each child running now."""
        with self._lock:
            return {n: c.proc.pid for n, c in self._children.items() if c.proc is not None and c.proc.poll() is None}

    def start(self) -> None:
        """Start every child and keep them running on a background thread until `stop`."""
        self.tick(time.monotonic())
        self._thread = threading.Thread(target=self._run, name="worker-supervisor", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._halt.wait(self._poll):
            self.tick(time.monotonic())

    def stop(self) -> None:
        """End every child, killing one still running `grace` seconds after it was asked to stop."""
        self._halt.set()
        with self._lock:
            running = [c.proc for c in self._children.values() if c.proc is not None]
            for proc in running:
                proc.terminate()
            deadline = time.monotonic() + self._grace
            for proc in running:
                try:
                    proc.wait(max(0.0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
