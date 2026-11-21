"""What the task actor remembers of a task between events, kept on the task's own record so a restart loses none of it."""

import copy
import hashlib
import logging
from collections.abc import Callable, Mapping
from typing import Any

from starpulse.board.model.seam import TaskReader, Written

logger = logging.getLogger(__name__)


def digest(key: Any) -> str:
    return hashlib.sha1(repr(key).encode()).hexdigest()[:12]


class TaskMemory:
    """The `actorMemory` mapping of each task's record: the resumes counted, the flags set and the holds kept.

    A task the board holds no record of, or cannot read, has none, and a write the board refuses is logged and leaves the memory as it
    was: the actor then acts on what the record held, as a restart would."""

    def __init__(self, read: TaskReader, write: Callable[[str, dict[str, Any]], Written]) -> None:
        self._read = read
        self._write = write

    def _record(self, name: str) -> Mapping[str, Any] | None:
        try:
            return self._read(name)
        except Exception as error:  # an unread board holds no memory: the actor acts as a fresh start would
            logger.warning("task actor: cannot read the memory of %s: %s", name, error)
            return None

    def of(self, name: str) -> dict[str, Any]:
        return copy.deepcopy((self._record(name) or {}).get("actorMemory") or {})

    def has(self, name: str, flag: str) -> bool:
        return flag in self.of(name)

    def keep(self, name: str, **changes: Any) -> None:
        """Set each change of `name`'s memory, a `None` removing its key, in one write that a no-change leaves out."""
        if (record := self._record(name)) is None:
            return
        memory = record.get("actorMemory") or {}
        kept = {key: copy.deepcopy(value) for key, value in {**memory, **changes}.items() if value is not None}
        if kept == memory:
            return
        written = self._write(name, kept)
        if not written.ok:
            logger.warning("task actor: the memory of %s was not kept: %s", name, written.output)

    def resumes(self, name: str, key: Any) -> tuple[bool, int]:
        """Whether the resumes counted on `name` were counted at `key`'s progress, and how many (none at another)."""
        held = self.of(name).get("resumes")
        if not held:
            return True, 0
        same = held[0] == digest(key)
        return same, held[1] if same else 0

    @staticmethod
    def tally(key: Any, resumes: int) -> list[Any]:
        return [digest(key), resumes]

    def count(self, name: str, key: Any, resumes: int) -> None:
        self.keep(name, resumes=self.tally(key, resumes))
