"""A write instance: the board of a config file served with its write routes, so a test writes tasks through StarPulse.

It is StarPulse's own assembly (`assembled`) over the config, so every Guard, the machine and the Board's validation
judge a test's write as they judge a served board's. The Board adapter scans the board's files onto the feed, `serve`
gives the feed its write routes, and `run` is a `starpulse` verb called in-process, ~100 times cheaper than a child
process.
"""

from __future__ import annotations

import contextlib
import io
import re
import subprocess
import tempfile
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

from starpulse.cli import agent_cli
from starpulse.runtime.config import load
from starpulse.runtime.store_migrate import maintain
from starpulse.board.adapters.upstream_backlog import _live
from starpulse.event_log.event_log import EventLog
from starpulse.runtime.adapter_kit import assembled, serve, url

#: How often the Board adapter rescans the board's files, so a task a write created is on the feed within a scan.
SCAN_INTERVAL_S = 0.05
#: How long a verb naming a task whose file exists waits for the feed to place it.
PLACED_WITHIN_S = 5.0
#: Held while an instance starts its adapter, so the threads that start is the only new ones in the adapter registry.
_STARTING = threading.Lock()
_MISSING = re.compile(r"([\w-]+) is not on the board")
_TASK_FOLDERS = ("tasks", "completed", "archive/tasks")


@dataclass(frozen=True)
class WriteInstance:
    """A running write instance: the board it writes, where it listens, and a way to run a `starpulse` verb against it."""

    board: Path
    url: str
    backlogs: tuple = field(default=(), compare=False, repr=False)

    def settle(self) -> None:
        """Place the board's files on the feed now, rather than at the Board adapter's next scan."""
        for backlog in self.backlogs:
            backlog.scan()

    def run(self, *argv: str) -> subprocess.CompletedProcess[str]:
        """Run `starpulse <argv> --server <url>` in this process and answer as a child process would.

        A task a verb created is placed on the feed by the adapter's next scan, so a verb that names a task whose file
        is already on the board is run again until the feed has it.
        """
        deadline = time.monotonic() + PLACED_WITHIN_S
        while True:
            done = self._once(argv)
            if not self._unplaced(done.stdout + done.stderr) or time.monotonic() > deadline:
                return done
            time.sleep(SCAN_INTERVAL_S)

    def _once(self, argv: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        out, err, code = io.StringIO(), io.StringIO(), 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = agent_cli.main([*argv, "--server", self.url]) or 0
            except SystemExit as stopped:
                code = stopped.code if isinstance(stopped.code, int) else int(stopped.code is not None)
        return subprocess.CompletedProcess(list(argv), code, stdout=out.getvalue(), stderr=err.getvalue())

    def _unplaced(self, reply: str) -> bool:
        missing = _MISSING.search(reply)
        if missing is None:
            return False
        return any(any((self.board / folder).glob(f"{missing[1]}[ -]*")) for folder in _TASK_FOLDERS)


@contextmanager
def write_instance(base: Path, config_file: str = "starpulse.toml") -> Generator[WriteInstance]:
    """Serve the write routes over the board `base / config_file` names, until the `with` block ends.

    `base` is the directory the config's relative paths are read from. The Board adapter rescans every
    `SCAN_INTERVAL_S` whatever the config sets.
    """
    config = load(base / config_file)
    config = replace(config, board={**config.board, "interval": SCAN_INTERVAL_S})
    board = base / str(config.board.get("path", "backlog"))
    with tempfile.TemporaryDirectory() as scratch:
        state = Path(scratch)
        stream, feed = assembled(config, base)
        store = f"sqlite:///{state / 'events.sqlite'}"
        maintain(store, feed.machines, config.event_log_retention_days)
        log = EventLog(store)
        with _STARTING:
            before = set(_live)
            stream.start(feed, "write-instance", log)
            started = {backlog: thread for backlog, thread in _live.items() if backlog not in before}
        try:
            with serve(state, feed, stream) as server:
                yield WriteInstance(board, url(server, ""), tuple(started))
        finally:
            for backlog, thread in started.items():
                backlog.stop()
                thread.join(PLACED_WITHIN_S)
            feed.stop(PLACED_WITHIN_S)
            log.close()
