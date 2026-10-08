"""The pull requests StarPulse read from GitHub, kept in its own store and served at `GET /api/pulls`."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import Engine, delete, insert, select

from starpulse.store.event_log import create_tables
from starpulse.store.tables import pull_requests

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


class PullStore:
    """Pull request records by (repository, number), in the database `engine` opens."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        create_tables(engine, [pull_requests])

    def save(self, records: Iterable[dict[str, Any]]) -> None:
        """Replace each record (served names, as `find` returns them) by its repository and number."""
        rows = [{column: record[name] for column, name in _FIELDS.items()} for record in records]
        if not rows:
            return
        with self._engine.begin() as db:
            for row in rows:
                db.execute(
                    delete(pull_requests).where(*(pull_requests.c[key] == row[key] for key in ("repo", "number")))
                )
            db.execute(insert(pull_requests), rows)

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
    ) -> list[dict[str, Any]]:
        """The records matching every given filter, by repository then number; `body_contains` is a body substring."""
        query = select(pull_requests).order_by(pull_requests.c.repo, pull_requests.c.number)
        for column, value in (("repo", repo), ("number", number), ("state", state)):
            if value is not None:
                query = query.where(pull_requests.c[column] == value)
        if body_contains:
            query = query.where(pull_requests.c.body.contains(body_contains, autoescape=True))
        with self._engine.connect() as db:
            return [{name: row[column] for column, name in _FIELDS.items()} for row in db.execute(query).mappings()]
