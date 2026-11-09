"""An ephemeral board: tasks written through StarPulse's write seam, and the records StarPulse reads back.

A downstream project builds the board its tests or evaluations run against with `ephemeral_board(seeds)` instead of
keeping a board harness of its own. It is `write_instance` over a scratch config, so every Guard, the machine and the
Board's validation judge a seed as they judge a served board's write, and each record is the `starpulse task show`
reply, the shape any client of the board reads.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Generator, Iterable
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from starpulse.runtime.write_instance import WriteInstance, write_instance

#: The config a board with no `starpulse.toml` of its own is served from: the default machine, the board at `board/`.
DEFAULT_CONFIG = '[board]\npath = "board"\n'


class EphemeralBoardError(RuntimeError):
    """A seed the board refused, or a record it could not read; carries the verb's reason."""


@dataclass(frozen=True)
class TaskSeed:
    """One task to open: its title and, optionally, its description, criteria and labels.

    `flags` is any other `starpulse task create` option, as argv (`("--status", "ready")`).
    """

    title: str
    description: str = ""
    criteria: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()

    def argv(self) -> list[str]:
        description = ["--description", self.description] if self.description else []
        criteria = [part for text in self.criteria for part in ("--ac", text)]
        labels = [part for label in self.labels for part in ("--label", label)]
        return ["task", "create", self.title, *description, *criteria, *labels, *self.flags]


@dataclass(frozen=True)
class EphemeralBoard:
    """A running board: its write instance, and the record of each seed in the order the seeds were given."""

    instance: WriteInstance
    records: tuple[dict, ...]

    def record(self, task: str) -> dict:
        """The task's record as the board holds it now, after any verb run through `instance`."""
        return _read(self.instance, task)


def _read(instance: WriteInstance, task: str) -> dict:
    instance.settle()  # a write reaches the feed at the adapter's next scan; place it now so the read sees it
    shown = instance.run("task", "show", task)
    if shown.returncode != 0:
        raise EphemeralBoardError(f"task show {task} exited {shown.returncode}: {shown.stdout}{shown.stderr}")
    return json.loads(shown.stdout)


def _open(instance: WriteInstance, seed: TaskSeed) -> dict:
    created = instance.run(*seed.argv())
    if created.returncode != 0:
        raise EphemeralBoardError(f"{seed.title!r} refused, exit {created.returncode}: {created.stdout}{created.stderr}")
    return _read(instance, json.loads(created.stdout)["task"])


@contextmanager
def ephemeral_board(seeds: Iterable[TaskSeed | str], base: Path | None = None) -> Generator[EphemeralBoard]:
    """Open a task per seed on a scratch board and serve it for the block; a bare string is a title.

    With no `base` the board lives in a temporary directory removed at the block's end. A `base` is kept: its
    `starpulse.toml` configures the board, else `DEFAULT_CONFIG` is written there, and the board's files stay after the
    block for the caller to read.
    """
    with ExitStack() as stack:
        if base is None:
            base = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        config = base / "starpulse.toml"
        if not config.exists():
            config.write_text(DEFAULT_CONFIG)
        instance = stack.enter_context(write_instance(base))
        opened = tuple(_open(instance, TaskSeed(seed) if isinstance(seed, str) else seed) for seed in seeds)
        yield EphemeralBoard(instance, opened)
