"""Count the rows a SQLAlchemy read pulls out of the database, so a test or benchmark can say how a read scales."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest import mock

from sqlalchemy.engine.cursor import CursorFetchStrategy


@contextmanager
def rows_fetched() -> Iterator[list[int]]:
    """A one-item list that holds the rows fetched through SQLAlchemy cursors inside the block, so far."""
    count = [0]
    fetch = {name: getattr(CursorFetchStrategy, name) for name in ("fetchone", "fetchmany", "fetchall")}

    def counting(name: str):
        def fetched(self, *args, **kwargs):
            rows = fetch[name](self, *args, **kwargs)
            count[0] += 0 if rows is None else len(rows) if name != "fetchone" else 1
            return rows

        return fetched

    with mock.patch.multiple(CursorFetchStrategy, **{name: counting(name) for name in fetch}):
        yield count
