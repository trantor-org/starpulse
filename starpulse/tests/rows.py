"""Count the rows a SQLAlchemy read pulls out of one engine, so a test or benchmark can say how a read scales."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest import mock

from sqlalchemy import Engine
from sqlalchemy.engine.cursor import CursorFetchStrategy


@contextmanager
def rows_fetched(engine: Engine) -> Iterator[list[int]]:
    """A one-item list that holds the rows fetched through `engine` inside the block, so far.

    Only `engine`'s results count: the patch is process-wide, and another store's reader thread would add to it.
    """
    count = [0]
    fetch = {name: getattr(CursorFetchStrategy, name) for name in ("fetchone", "fetchmany", "fetchall")}

    def counting(name: str):
        def fetched(self, result, *args, **kwargs):
            rows = fetch[name](self, result, *args, **kwargs)
            if result.connection.engine is engine and rows is not None:
                count[0] += 1 if name == "fetchone" else len(rows)
            return rows

        return fetched

    with mock.patch.multiple(CursorFetchStrategy, **{name: counting(name) for name in fetch}):
        yield count
