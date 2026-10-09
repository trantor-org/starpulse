"""The pull requests StarPulse read from GitHub, kept in its own store and served at `GET /api/pulls`."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import Engine, case, delete, func, inspect, insert, select, text

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
    "fetched_at": "fetchedAt",
}


AGE_METRIC = "starpulse_pull_store_age_seconds"
AGE_HELP = "Seconds since the newest pull request record of a repository was read from GitHub."


class PullStore:
    """Pull request records by (repository, number), in the database `engine` opens."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        #: Counts saves, so a reader holding an answer knows when it is stale.
        self.rev = 0
        create_tables(engine, [pull_requests])
        if "detail" not in {column["name"] for column in inspect(engine).get_columns(pull_requests.name)}:
            with engine.begin() as db:  # a table an earlier version created: the hub's migration 0010 adds it there
                db.execute(text(f"ALTER TABLE {pull_requests.name} ADD COLUMN detail JSON"))

    def save(self, records: Iterable[dict[str, Any]]) -> None:
        """Replace each record (served names, as `find` returns them, and a `detail` when it has one) by its repository
        and number."""
        rows = [
            {**{column: record[name] for column, name in _FIELDS.items()}, "detail": record.get("detail")}
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
        self.rev += 1

    def repos(self) -> list[str]:
        """The repositories the store holds a record of."""
        with self._engine.connect() as db:
            return list(db.execute(select(pull_requests.c.repo).distinct().order_by(pull_requests.c.repo)).scalars())

    def age_gauge(self, now: float) -> str:
        """Prometheus text of the seconds since each repository's newest record was read, as of epoch `now`.

        A refresh rewrites only the open and the changed PRs, so only a repository holding an open one is
        re-read every cycle; one with none ages without being stale and is left out."""
        newest = (
            select(pull_requests.c.repo, func.max(pull_requests.c.fetched_at).label("newest"))
            .group_by(pull_requests.c.repo)
            .having(func.sum(case((pull_requests.c.state == "OPEN", 1), else_=0)) > 0)
            .order_by(pull_requests.c.repo)
        )
        with self._engine.connect() as db:
            rows = db.execute(newest).all()
        samples = [f'{AGE_METRIC}{{repo="{repo}"}} {now - fetched:g}' for repo, fetched in rows]
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
        query = select(pull_requests).order_by(pull_requests.c.repo, pull_requests.c.number)
        for column, value in (("repo", repo), ("number", number), ("state", state)):
            if value is not None:
                query = query.where(pull_requests.c[column] == value)
        if body_contains:
            query = query.where(pull_requests.c.body.contains(body_contains, autoescape=True))
        with self._engine.connect() as db:
            return [
                {name: row[column] for column, name in _FIELDS.items()} | ({"detail": row["detail"]} if detailed else {})
                for row in db.execute(query).mappings()
            ]
