"""The insights API: `POST /api/insights` and `DELETE /api/insights/<id>`, the fourth contract.

An external engine (a separate package; this one holds no engine code) posts one `Finding` as JSON, with
`Authorization: Bearer <engine token>`; a hub names that token's variable as `engine_token_env` in its `[oidc]` table, and
a server without one has no insights routes (404). The engine token is checked before a request reaches this module
(`oidc.Gate`) and is no forwarder token and no viewer's sign-in.

The answers: 201 `{id, replaced: false}` for a new finding, 200 `{id, replaced: true}` when the id was held and not
retracted, so a re-post replaces it; 400 naming the field to fix for a body the contract refuses, including a scope that
names a person, since the contract has no person field; 413 over 64 KiB; 503 when the history store refuses it. A
retraction answers 200 `{id, retracted: true}`, or 404 for an id that is unknown or already retracted. A refusal writes
and sends nothing.

Each state reaches the history store (`starpulse_insights`, kept after a retraction) and the page: `/api/events` sends an
`insight` event `{id, finding}` for a post or re-post and `{id, finding: null}` for a retraction, and its snapshot lists
the `insights` that are live, so a page that connects later draws them. A finding past its `expires_at` is not drawn,
and a hub that restarts draws the live ones again from the store (`restore`).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import SQLAlchemyError

from starpulse.board_feed import BoardFeed
from starpulse.contracts import Finding
from starpulse.event_log import create_tables
from starpulse.tables import insights as table

__all__ = ["Insights", "InsightStore", "restore"]


def _row(finding: Finding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "engine_name": finding.engine.name,
        "engine_version": finding.engine.version,
        **{field: getattr(finding.scope, field) for field in ("team", "machine", "state", "task")},
        "severity": finding.severity,
        "text": finding.text,
        "evidence": [e.model_dump(mode="json", exclude_none=True) for e in finding.evidence],
        "created_at": finding.created_at,
        "expires_at": finding.expires_at,
        "retracted_at": None,
    }


def _finding(row: Any) -> Finding:
    return Finding.model_validate(
        {
            "id": row.id,
            "engine": {"name": row.engine_name, "version": row.engine_version},
            "scope": {field: getattr(row, field) for field in ("team", "machine", "state", "task")},
            "severity": row.severity,
            "text": row.text,
            "evidence": row.evidence,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
        }
    )


class InsightStore:
    """The findings in the history database: one row per id, replaced by a re-post and marked, not deleted, when retracted."""

    def __init__(self, url: str, engine: Engine | None = None) -> None:
        self.engine = engine or create_engine(url)
        # pragma: no mutate start — SQLite compiles the postgresql insert's ON CONFLICT alike
        self._dialect = postgresql if self.engine.dialect.name == "postgresql" else sqlite
        # pragma: no mutate end
        create_tables(self.engine)

    def put(self, finding: Finding) -> bool:
        """Write `finding`, replacing the row of its id and reviving a retracted one; whether it replaced a row not
        retracted."""
        values = _row(finding)
        insert = self._dialect.insert(table).values(values)
        with self.engine.begin() as db:
            held = db.execute(select(table.c.retracted_at).where(table.c.id == finding.id)).first()
            db.execute(
                insert.on_conflict_do_update(
                    index_elements=["id"], set_={name: insert.excluded[name] for name in values if name != "id"}
                )
            )
        return held is not None and held.retracted_at is None

    def retract(self, finding_id: str, at: float) -> bool:
        """Mark the finding retracted at `at`; False when no such finding is held or it was retracted already."""
        with self.engine.begin() as db:
            done = db.execute(
                update(table).where(table.c.id == finding_id, table.c.retracted_at.is_(None)).values(retracted_at=at)
            )
        return done.rowcount > 0

    def live(self, now: float) -> list[Finding]:
        """The findings neither retracted nor expired at `now`, oldest first."""
        live = table.c.retracted_at.is_(None) & (table.c.expires_at.is_(None) | (table.c.expires_at > now))
        with self.engine.connect() as db:
            rows = db.execute(select(table).where(live).order_by(table.c.created_at, table.c.id)).all()
        return [_finding(row) for row in rows]


def _refusal(exc: ValidationError) -> str:
    """The fields to fix, each with where it is and what is wrong with it."""
    errors = exc.errors()
    reasons = "; ".join(f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}" for e in errors)
    if any(e["type"] == "extra_forbidden" for e in errors):
        reasons += " (a finding holds only the fields the contract names; it has no field for a person)"
    return reasons


class Insights:
    """Answers the two insights routes: the finding or id to its `(status, JSON body)`."""

    def __init__(self, store: InsightStore, feed: BoardFeed, clock: Callable[[], float] = time.time) -> None:
        self._store, self._feed, self._clock = store, feed, clock

    def __call__(self, _authorization: str | None, raw: bytes) -> tuple[int, dict[str, Any]]:
        """Answer a pushed body as `Ingest` does; the gate has already checked the engine token, so the header is unread."""
        return self.post(raw)

    def post(self, raw: bytes) -> tuple[int, dict[str, Any]]:
        try:
            body = json.loads(raw)
        except ValueError:
            return 400, {"error": "the body is not JSON"}
        if not isinstance(body, dict):
            return 400, {"error": "the body must be a JSON object holding one finding"}
        try:
            finding = Finding.model_validate(body)
        except ValidationError as exc:
            return 400, {"error": _refusal(exc)}
        try:
            replaced = self._store.put(finding)
        except SQLAlchemyError:
            return 503, {"error": "the history store refused the finding; retry"}
        self._feed.put_insight(finding.model_dump(mode="json"))
        return (200 if replaced else 201), {"id": finding.id, "replaced": replaced}

    def retract(self, finding_id: str) -> tuple[int, dict[str, Any]]:
        try:
            retracted = self._store.retract(finding_id, self._clock())
        except SQLAlchemyError:
            return 503, {"error": "the history store refused the retraction; retry"}
        if not retracted:
            return 404, {"error": f"no live finding {finding_id}"}
        self._feed.retract_insight(finding_id)
        return 200, {"id": finding_id, "retracted": True}


def restore(store: InsightStore, feed: BoardFeed, now: float | None = None) -> None:
    """Draw every finding still live at `now` (the clock by default), as a hub does when it starts."""
    for finding in store.live(time.time() if now is None else now):
        feed.put_insight(finding.model_dump(mode="json"))
