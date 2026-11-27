"""The native board's doc index: the store's `starpulse_doc_index` rows, one per doc file, and the reads and writes of them.

A path is relative to the board's root, so `docs/` or `archive/docs/` says whether the doc is archived. Nothing here
reads a doc file: a lookup is a query, so a moved doc of any file type is found by its id.
"""

from collections import Counter
from functools import cache
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import Engine, case, delete, insert, select

from starpulse.event_log.tables import doc_index

ARCHIVE = "archive/docs/"


class Entry(NamedTuple):
    path: str
    id: str
    title: str
    type: str


class DocIndex:
    """The doc index of the board at `root`, backed by the store once `engine` is set when the board attaches its log."""

    def __init__(self, root: Path, engine: Engine | None = None) -> None:
        self.root = root
        self.engine = engine

    def _rows(self, *clauses, ordered: bool = False) -> list[Entry]:
        if self.engine is None:
            return []
        query = select(doc_index.c.path, doc_index.c.id, doc_index.c.title, doc_index.c.type).where(*clauses)
        if ordered:  # an open doc before an archived one, then by path
            query = query.order_by(case((doc_index.c.path.like(f"{ARCHIVE}%"), 1), else_=0), doc_index.c.path)
        with self.engine.connect() as db:
            return [Entry(*row) for row in db.execute(query)]

    def find(self, doc: str, archived: bool) -> Entry | None:
        """The open (or archived) doc `doc` names: a path under `docs/` (the record's `path`) before an id, which an
        archived doc may share with another."""
        folder = ARCHIVE if archived else "docs/"
        by_path = self._rows(doc_index.c.path == folder + doc)
        found = by_path or [
            entry for entry in self._rows(doc_index.c.id == doc, ordered=True) if entry.path.startswith(folder)
        ]
        return found[0] if found else None

    def entries(self) -> list[Entry]:
        return self._rows()

    def counts(self) -> Counter[str]:
        """The open docs by type."""
        return Counter(entry.type for entry in self._rows(doc_index.c.path.like("docs/%")))

    def highest(self) -> int:
        """The number of the highest id the index holds, archived docs included."""
        numbers = (entry.id.removeprefix("doc-") for entry in self._rows())
        return max((int(number) for number in numbers if number.isdigit()), default=0)

    def put(self, entries: Iterable[Entry], replacing: str | None = None) -> None:
        """Write the rows of `entries`, each replacing the row of its path; `replacing` names a path whose row goes in the
        same transaction, so a doc that moved or renamed has one row at every moment."""
        if self.engine is None:
            raise OSError("the doc index is not open")
        rows = [entry._asdict() for entry in entries]
        gone = [row["path"] for row in rows] + ([replacing] if replacing is not None else [])
        with self.engine.begin() as db:
            db.execute(delete(doc_index).where(doc_index.c.path.in_(gone)))
            if rows:
                db.execute(insert(doc_index), rows)


@cache
def index_of(root: Path) -> DocIndex:
    """The one doc index of the board at `root`, which the board's writers and a task's references share."""
    return DocIndex(root)
