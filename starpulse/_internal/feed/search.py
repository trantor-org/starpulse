"""Full-text search over the board's tasks, kept in the instance's own database.

The index is an SQLite FTS5 table of each placed task's id, title, description, acceptance criteria and notes. It lives
beside the event log on the instance and never on a hub (individual data stays on the instance). A row is keyed by a
rowid derived from the task id, so replacing a task and reading its stored digest are point lookups, and a task placed
again unchanged, as every task is on a restart, writes nothing.
"""

from __future__ import annotations

import hashlib
import logging
import threading

from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from starpulse.contracts.adapters import BoardTask

logger = logging.getLogger(__name__)

_TABLE = "starpulse_task_search"
_CREATE = (
    f"CREATE VIRTUAL TABLE IF NOT EXISTS {_TABLE} USING fts5("
    "task, title, description, criteria, notes, lane UNINDEXED, digest UNINDEXED, tokenize = 'porter unicode61')"
)
#: What a match in each column is worth, in the column order above: a title says most, a note least.
_WEIGHTS = "4, 10, 2, 1, 1, 0, 0"
_SEARCH = text(
    f"SELECT task, title, lane, -bm25({_TABLE}, {_WEIGHTS}) AS score, snippet({_TABLE}, -1, '', '', '…', 16) AS snippet "
    f"FROM {_TABLE} WHERE {_TABLE} MATCH :query ORDER BY bm25({_TABLE}, {_WEIGHTS}), task LIMIT :limit"
)
_DIGEST = text(f"SELECT digest FROM {_TABLE} WHERE rowid = :row")
_DELETE = text(f"DELETE FROM {_TABLE} WHERE rowid = :row")
_INSERT = text(
    f"INSERT INTO {_TABLE} (rowid, task, title, description, criteria, notes, lane, digest) "
    "VALUES (:row, :task, :title, :description, :criteria, :notes, :lane, :digest)"
)


def _row(task_id: str) -> int:
    """The index's rowid for a task: 56 bits of its id's hash, so a collision between two tasks of a board is a
    one-in-ten-billion event."""
    return int.from_bytes(hashlib.blake2b(task_id.encode(), digest_size=7).digest(), "big")


def _match(query: str) -> str:
    """`query` as an FTS5 expression of quoted words, all of which a task must hold, so its punctuation is text and
    never FTS5 syntax (`PROJ-45`, `NEAR`, `title:`)."""
    return " ".join('"' + word.replace('"', '""') + '"' for word in query.split())


class SearchIndex:
    """An FTS5 index of each placed task's id, title, description, acceptance criteria and notes."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._lock = threading.Lock()

    @classmethod
    def open(cls, engine: Engine) -> SearchIndex | None:
        """The index in `engine`'s database, created when absent; None for a database that is not SQLite or whose
        SQLite was built without FTS5, which then keeps no search."""
        if engine.dialect.name != "sqlite":
            return None
        try:
            with engine.begin() as connection:
                connection.execute(text(_CREATE))
        except OperationalError as error:
            logger.warning("StarPulse: this SQLite has no FTS5, so the board is not searchable: %s", error)
            return None
        return cls(engine)

    def index(self, task: BoardTask) -> None:
        """Make the index hold `task` as it is now; a task already held unchanged is left alone."""
        lane = task.settled or task.lane
        fields = {
            "task": task.id,
            "title": task.title,
            "description": task.description,
            "criteria": "\n".join(task.acceptance_criteria),
            "notes": task.notes,
            "lane": lane,
        }
        digest = hashlib.sha256("\x1f".join(fields.values()).encode()).hexdigest()
        row = _row(task.id)
        with self._lock, self._engine.begin() as connection:
            if connection.execute(_DIGEST, {"row": row}).scalar() == digest:
                return
            connection.execute(_DELETE, {"row": row})
            connection.execute(_INSERT, {"row": row, "digest": digest, **fields})

    def remove(self, task_id: str) -> None:
        """Drop `task_id` from the index; a task the index does not hold is a no-op."""
        with self._lock, self._engine.begin() as connection:
            connection.execute(_DELETE, {"row": _row(task_id)})

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """The tasks holding every word of `query`, best first, as `{task, title, lane, score, snippet}`; `score` is
        higher for a better match and `snippet` is the text around it."""
        match = _match(query)
        if not match:
            return []
        with self._engine.connect() as connection:
            rows = connection.execute(_SEARCH, {"query": match, "limit": max(1, limit)})
            return [dict(row._mapping) for row in rows]
