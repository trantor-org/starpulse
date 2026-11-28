"""A write instance: the board of a config file served with its write routes, so a test writes tasks through StarPulse.

It is StarPulse's own assembly (`assembled`) over the config, so every Guard, the machine and the Board's validation
judge a test's write as they judge a served board's. The History a read
model over a temporary database folds holds each task, `serve` gives the feed over it its write routes, and `run` is a `starpulse` verb called in-process, ~100 times cheaper than a child
process.
"""

import contextlib
import io
import subprocess
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from starpulse.cli import agent_cli
from starpulse.event_log.wake import StopEvent
from starpulse.runtime.serve_kit import FOLDED_WITHIN_S, serve, url
from starpulse.runtime.config import load
from starpulse.runtime.placed import Placed, assembled

#: How long a stopped instance waits for the feed's threads to end.
PLACED_WITHIN_S = 5.0


@dataclass(frozen=True)
class WriteInstance:
    """A running write instance: the board it writes, where it listens, and a way to run a `starpulse` verb against it."""

    board: Path
    url: str
    caught_up: Callable[[float], bool] = field(compare=False, repr=False)
    placed: Placed | None = field(default=None, compare=False, repr=False)

    def settle(self) -> None:
        """Fold the History appended so far, and wait for the Board writer to fold it into the snapshot a read is served from."""
        self._fold()
        if not self.caught_up(FOLDED_WITHIN_S):
            raise TimeoutError(f"the Board writer folded no change in {FOLDED_WITHIN_S} s")

    def _fold(self) -> None:
        if self.placed is not None:
            self.placed.fold()

    def run(self, *argv: str) -> subprocess.CompletedProcess[str]:
        """Run `starpulse <argv> --server <url>` in this process and answer as a child process would."""
        return self._once(argv)

    def _once(self, argv: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        out, err, code = io.StringIO(), io.StringIO(), 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = agent_cli.main([*argv, "--server", self.url]) or 0
            except SystemExit as stopped:
                code = stopped.code if isinstance(stopped.code, int) else int(stopped.code is not None)
        self._fold()  # the verb's write is History the feed reads once folded
        return subprocess.CompletedProcess(list(argv), code, stdout=out.getvalue(), stderr=err.getvalue())


@contextmanager
def write_instance(base: Path, config_file: str = "starpulse.toml") -> Generator[WriteInstance]:
    """Serve the write routes over the board `base / config_file` names, until the `with` block ends.

    `base` is the directory the config's relative paths are read from.
    """
    config = load(base / config_file)
    board = base / str(config.board.get("path", "backlog"))
    stream, feed, placed = assembled(config, base)
    stop = StopEvent()
    placed.follow(stop)
    feed.ready.set()
    stream.start(feed, "write-instance", placed.log)
    try:
        with tempfile.TemporaryDirectory() as scratch, serve(Path(scratch), feed, stream) as server:
            yield WriteInstance(board, url(server, ""), server.caught_up, placed)
    finally:
        stop.set()
        feed.stop(PLACED_WITHIN_S)
