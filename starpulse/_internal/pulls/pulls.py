"""The pull requests StarPulse read from GitHub, kept in its own store and served at `GET /api/pulls`."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import Engine, case, delete, func, insert, select, tuple_

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


AGE_METRIC = "starpulse_pull_store_age_seconds"
AGE_HELP = "Seconds since GitHub was last read successfully for a repository holding an open pull request."


class PullStore:
    """Pull request records by (repository, number), in the database `engine` opens.

    Reads are served from memory: `sqlite3` gives up the GIL at every row step, and beside a thread that computes, each
    step waits its turn again, so a 1,968-row read took 12-45 s on a busy server (TASK-5076). Every write passes
    through `save`, which keeps the copy current; a record a caller changes in place changes what a later read serves."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        #: Counts saves, so a reader holding an answer knows when it is stale.
        self.rev = 0
        self._lock = threading.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._checked: dict[str, float] = {}
        create_tables(engine, [pull_requests])
        self._held: dict[tuple[str, int], dict[str, Any]] = {}
        self._hold(select(pull_requests))

    def _hold(self, query: Any) -> None:
        """Take the rows `query` selects into memory, replacing each held record of the same repository and number."""
        with self._engine.connect() as db:
            rows = [
                {name: row[column] for column, name in (_FIELDS | _LATER).items()} | {"detail": row["detail"]}
                for row in db.execute(query).mappings()
            ]
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
        self._hold(
            select(pull_requests).where(
                tuple_(pull_requests.c.repo, pull_requests.c.number).in_([(row["repo"], row["number"]) for row in rows])
            )
        )
        self.rev += 1
        for listener in self._listeners:
            listener()

    def subscribe(self, listener: Callable[[], None]) -> None:
        """Call `listener` in the saving thread after each save, so an answer built from the store is ready before a
        reader asks for it."""
        self._listeners.append(listener)

    def repos(self) -> list[str]:
        """The repositories the store holds a record of."""
        with self._engine.connect() as db:
            return list(db.execute(select(pull_requests.c.repo).distinct().order_by(pull_requests.c.repo)).scalars())

    def mark_checked(self, repo: str, now: float) -> None:
        """Note that GitHub answered a read of `repo` at epoch `now`, though no record changed."""
        self._checked[repo] = now

    def age_gauge(self, now: float) -> str:
        """Prometheus text of the seconds since GitHub was last read for each repository, as of epoch `now`: the
        later of its newest record's read and its last `mark_checked`, since a listing that agrees with the store
        rewrites nothing.

        Only a repository holding an open PR is polled every cycle; one with none ages without being stale and is
        left out."""
        newest = (
            select(pull_requests.c.repo, func.max(pull_requests.c.fetched_at).label("newest"))
            .group_by(pull_requests.c.repo)
            .having(func.sum(case((pull_requests.c.state == "OPEN", 1), else_=0)) > 0)
            .order_by(pull_requests.c.repo)
        )
        with self._engine.connect() as db:
            rows = db.execute(newest).all()
        samples = [
            f'{AGE_METRIC}{{repo="{repo}"}} {now - max(fetched, self._checked.get(repo, fetched)):g}'
            for repo, fetched in rows
        ]
        return "\n".join([f"# HELP {AGE_METRIC} {AGE_HELP}", f"# TYPE {AGE_METRIC} gauge", *samples]) + "\n"

    def find(
        self,
        repo: str | None = None,
        number: int | None = None,
        state: str | None = None,
        body_contains: str | None = None,
        detailed: bool = False,
    ) -> list[dict[str, Any]]:
        """The records matching every given filter, by repository then number; `body_contains` is a body substring.

        `detailed` adds each record's `detail`, which is not served: None for a record saved before it was kept."""
        needle = body_contains.lower() if body_contains else None  # SQLite's LIKE ignores ASCII case
        with self._lock:
            held = sorted(self._held.items())
        return [
            {name: value for name, value in record.items() if detailed or name != "detail"}
            for _, record in held
            if repo in (None, record["repo"])
            and number in (None, record["number"])
            and state in (None, record["state"])
            and (needle is None or needle in record["body"].lower())
        ]
