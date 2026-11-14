"""The policy tables of StarPulse's store, and the loader that reads them.

A store whose policy tables are all empty is governed by today's files: `load` then answers the policy `files` builds.
The tables are written by a migration (the operator's own chain, a later slice), never by StarPulse at runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    Connection,
    Engine,
    Integer,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    create_engine,
    inspect,
    select,
)
from sqlalchemy.engine import make_url

from starpulse.board.model.policy import Exit, Lane, LaneTool, Policy, PolicyRule, Profile, Route, Vocabulary, Watch
from starpulse.event_log.tables import metadata

__all__ = ["exits", "held", "lanes", "load", "profiles", "routes", "rules", "stored", "tools", "vocabularies", "watches"]

lanes = Table(
    "starpulse_policy_lanes",
    metadata,
    Column("name", String, primary_key=True),
    Column("role", String),
    Column("position", Integer, nullable=False),
    Column("skill", String),
)
routes = Table(
    "starpulse_policy_routes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event", String, nullable=False),
    Column("source", String, nullable=False),
    Column("target", String, nullable=False),
    Column("condition", JSON),
)
exits = Table(
    "starpulse_policy_exits",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event", String, nullable=False),
    Column("actor", String, nullable=False),
    Column("trigger", String, nullable=False),
)
watches = Table(
    "starpulse_policy_watches",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("lane", String, nullable=False),
    Column("fact", String, nullable=False),
    Column("event", String, nullable=False),
    Column("position", Integer, nullable=False),
)
rules = Table(
    "starpulse_policy_rules",
    metadata,
    Column("position", Integer, primary_key=True, autoincrement=False),
    Column("on", JSON, nullable=False),
    Column("require", JSON, nullable=False),
    Column("reason", Text, nullable=False),
    Column("skill", String, nullable=False),
    Column("unless_actor", JSON, nullable=False),
)
vocabularies = Table(
    "starpulse_policy_vocabularies",
    metadata,
    Column("name", String, nullable=False),
    Column("value", String, nullable=False),
    Column("position", Integer, nullable=False),
    PrimaryKeyConstraint("name", "value"),
)
profiles = Table(
    "starpulse_policy_profiles",
    metadata,
    Column("kind", String, nullable=False),
    Column("size", Integer, nullable=False),
    Column("profile", String, nullable=False),
    PrimaryKeyConstraint("kind", "size"),
)
tools = Table(
    "starpulse_policy_tools",
    metadata,
    Column("lane", String, nullable=False),
    Column("tool", String, nullable=False),
    PrimaryKeyConstraint("lane", "tool"),
)

#: Each table's row type and the order its rows are read in.
_READ: tuple[tuple[Table, type, Any], ...] = (
    (lanes, Lane, lanes.c.position),
    (routes, Route, routes.c.id),
    (exits, Exit, exits.c.id),
    (watches, Watch, (watches.c.lane, watches.c.position)),
    (rules, PolicyRule, rules.c.position),
    (vocabularies, Vocabulary, (vocabularies.c.name, vocabularies.c.position)),
    (profiles, Profile, (profiles.c.kind, profiles.c.size)),
    (tools, LaneTool, (tools.c.lane, tools.c.tool)),
)


def stored(db: Connection) -> Policy:
    """The policy the store's tables hold; empty when they hold none."""
    held = []
    for table, row, order in _READ:
        query = select(*(table.c[field.name] for field in fields(row))).order_by(*(order if isinstance(order, tuple) else (order,)))
        held.append(tuple(row(**record._mapping) for record in db.execute(query)))
    return Policy(*held)


def load(engine: Engine, files: Callable[[], Policy]) -> tuple[str, Policy]:
    """The policy that governs: `("database", policy)` when the store holds any, else `("files", files())`."""
    with engine.connect() as db:
        held = stored(db)
    return ("database", held) if held != Policy() else ("files", files())


def held(url: str) -> Policy:
    """The policy the store at `url` holds; empty when the store is absent or not yet migrated, which leaves the board
    with no guard, profile cell or watch until the policy chain fills it. A SQLite file that does not exist is not created;
    any other database error propagates, so a board never starts unguarded on a fault."""
    target = make_url(url)
    if target.get_backend_name() == "sqlite" and target.database not in (None, ":memory:") and not Path(target.database).exists():
        return Policy()
    engine = create_engine(url)
    try:
        with engine.connect() as db:
            return stored(db) if inspect(db).has_table(lanes.name) else Policy()
    finally:
        engine.dispose()
