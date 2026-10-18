"""The pull requests StarPulse keeps in its own store, projected from lifecycle events, and serves at `GET /api/pulls`."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, delete, insert, or_, select, tuple_

from starpulse._internal.eventlog.event_log import create_tables
from starpulse._internal.eventlog.tables import pull_requests

#: The GraphQL names a record is served under, by column.
_FIELDS = {
    "repo": "repo",
    "number": "number",
    "state": "state",
    "is_draft": "isDraft",
    "mergeable": "mergeable",
    "base": "baseRefName",
    "head": "headRefOid",
    "body": "body",
    "checks": "checks",
    "required": "requiredChecks",
    "threads": "threads",
    "updated_at": "updatedAt",
    "merged_at": "mergedAt",
    "merge_sha": "mergeSha",
    "fetched_at": "fetchedAt",
}
#: The names of columns an older refresh did not fill: a record may lack them, and is served with them null.
_LATER = {"head_ref": "headRefName", "unresolved": "unresolvedThreads"}


#: How long after its last update a closed or merged pull request stays in memory: about 250 a day, 12 KB each.
HOLD_WINDOW = timedelta(hours=24)


class PullStore:
    """Pull request records by (repository, number), in the database `engine` opens.

    Reads are served from memory: `sqlite3` gives up the GIL at every row step, and beside a thread that computes, each
    step waits its turn again, so a 1,968-row read took 12-45 s on a busy server (TASK-5076). Memory holds the open
    records, those updated within `window` and each one saved since; `find` reads the rest from the database only when
    a query can reach them. Every write passes through `save`, which keeps the copy current; a record a caller changes
    in place changes what a later read serves."""

    def __init__(self, engine: Engine, window: timedelta = HOLD_WINDOW) -> None:
        self._engine = engine
        #: Counts saves, so a reader holding an answer knows when it is stale.
        self.rev = 0
        self._lock = threading.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._save_listeners: list[Callable[[list[tuple[str, int]]], None]] = []
        create_tables(engine, [pull_requests])
        self._held: dict[tuple[str, int], dict[str, Any]] = {}
        since = (datetime.now(UTC) - window).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._hold(
            select(pull_requests).where(or_(pull_requests.c.state == "OPEN", pull_requests.c.updated_at >= since))
        )

    def _read(self, query: Any) -> list[dict[str, Any]]:
        """The records of the rows `query` selects, with their `detail`."""
        with self._engine.connect() as db:
            return [
                {name: row[column] for column, name in (_FIELDS | _LATER).items()} | {"detail": row["detail"]}
                for row in db.execute(query).mappings()
            ]

    def _hold(self, query: Any) -> None:
        """Take the rows `query` selects into memory, replacing each held record of the same repository and number."""
        rows = self._read(query)
        with self._lock:
            self._held.update({(row["repo"], row["number"]): row for row in rows})

    def save(self, records: Iterable[dict[str, Any]]) -> None:
        """Replace each record (served names, as `find` returns them, and a `detail` when it has one) by its repository
        and number."""
        rows = [
            {
                **{column: record[name] for column, name in _FIELDS.items()},
                **{column: record.get(name) for column, name in _LATER.items()},
                "detail": record.get("detail"),
            }
            for record in records
        ]
        if not rows:
            return
        with self._engine.begin() as db:
            for row in rows:
                db.execute(
                    delete(pull_requests).where(*(pull_requests.c[key] == row[key] for key in ("repo", "number")))
                )
            db.execute(insert(pull_requests), rows)
        keys = [(row["repo"], row["number"]) for row in rows]
        self.refresh(keys)
        for announce in self._save_listeners:
            announce(keys)

    def refresh(self, keys: Iterable[tuple[str, int]]) -> None:
        """Take the database's rows of `keys` (repository, number) into memory, as after a save: the way a process that
        does not write the store sees what another one saved."""
        self._hold(select(pull_requests).where(tuple_(pull_requests.c.repo, pull_requests.c.number).in_(list(keys))))
        self.rev += 1
        for listener in self._listeners:
            listener()

    def subscribe(self, listener: Callable[[], None]) -> None:
        """Call `listener` in the refreshing thread after each save or refresh, so an answer built from the store is
        ready before a reader asks for it."""
        self._listeners.append(listener)

    def subscribe_saves(self, listener: Callable[[list[tuple[str, int]]], None]) -> None:
        """Call `listener` with the keys of each save this store makes, never of a refresh, so the other processes
        holding the store can refresh them."""
        self._save_listeners.append(listener)

    def repos(self) -> list[str]:
        """The repositories the store holds a record of."""
        with self._engine.connect() as db:
            return list(db.execute(select(pull_requests.c.repo).distinct().order_by(pull_requests.c.repo)).scalars())

    def find(
        self,
        repo: str | None = None,
        number: int | None = None,
        state: str | None = None,
        body_contains: str | None = None,
        detailed: bool = False,
        held_only: bool = False,
    ) -> list[dict[str, Any]]:
        """The records matching every given filter, by repository then number; `body_contains` is a body substring.

        `detailed` adds each record's `detail`, which is not served: None for a record saved before it was kept.
        `held_only` leaves out the records only the database holds, so the read runs no SQL."""
        needle = body_contains.lower() if body_contains else None  # SQLite's LIKE ignores ASCII case
        with self._lock:
            held = dict(self._held)
        found = [
            record
            for record in held.values()
            if repo in (None, record["repo"])
            and number in (None, record["number"])
            and state in (None, record["state"])
            and (needle is None or needle in record["body"].lower())
        ]
        if not held_only and state != "OPEN" and (repo is None or number is None or (repo, number) not in held):
            found += self._stored(held, repo, number, state, needle)
        return [
            {name: value for name, value in record.items() if detailed or name != "detail"}
            for record in sorted(found, key=lambda record: (record["repo"], record["number"]))
        ]

    def _stored(
        self,
        held: dict[tuple[str, int], dict[str, Any]],
        repo: str | None,
        number: int | None,
        state: str | None,
        needle: str | None,
    ) -> list[dict[str, Any]]:
        """The records in the database matching the filters that are not in `held`."""
        filters = {"repo": repo, "number": number, "state": state}
        query = select(pull_requests).where(
            *(pull_requests.c[key] == value for key, value in filters.items() if value is not None)
        )
        if needle:
            query = query.where(pull_requests.c.body.contains(needle, autoescape=True))
        return [record for record in self._read(query) if (record["repo"], record["number"]) not in held]
