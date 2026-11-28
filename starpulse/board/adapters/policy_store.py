"""The policy tables of StarPulse's store, and the loader that reads them.

Policy is stored like machines: `starpulse_policy_versions` keeps every policy ever activated by the hash of its document, and
`starpulse_policy_active` names the one that governs. A store whose active row is absent holds no policy and is governed by
today's files: `load` then answers the policy `files` builds. `write` adds a version and activates it; the operator's chain
and a later API route are its writers.
"""

import json
import time
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

from sqlalchemy import JSON, Column, Connection, Engine, Float, ForeignKey, Integer, String, Table, create_engine, delete, inspect, insert, select
from sqlalchemy.engine import make_url

from starpulse.board.model.policy import Policy
from starpulse.board.model.policy_diff import policy_of, rows
from starpulse.event_log.tables import metadata

__all__ = ["active", "held", "load", "stored", "versions", "write"]

#: Every policy ever activated, kept by the hash of its document (the table rows `rows` gives). Nothing prunes or rewrites it.
versions = Table(
    "starpulse_policy_versions",
    metadata,
    Column("hash", String, primary_key=True),
    Column("document", JSON, nullable=False),
    Column("created_at", Float, nullable=False),
)
#: The version that governs: one row, `id` 1.
active = Table(
    "starpulse_policy_active",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("hash", String, ForeignKey("starpulse_policy_versions.hash"), nullable=False),
    Column("activated_at", Float, nullable=False),
)


def stored(db: Connection) -> Policy:
    """The policy the active version holds; empty when none is active."""
    document = db.execute(select(versions.c.document).join(active, active.c.hash == versions.c.hash)).scalar()
    return policy_of(document) if document is not None else Policy()


def write(db: Connection, policy: Policy) -> str:
    """Add `policy` as a version unless the store has it, make it the active one, and return its hash."""
    document = rows(policy)
    digest = sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
    now = time.time()
    if db.execute(select(versions.c.hash).where(versions.c.hash == digest)).scalar() is None:
        db.execute(insert(versions).values(hash=digest, document=document, created_at=now))
    db.execute(delete(active))
    db.execute(insert(active).values(id=1, hash=digest, activated_at=now))
    return digest


def load(engine: Engine, files: Callable[[], Policy]) -> tuple[str, Policy]:
    """The policy that governs: `("database", policy)` when the store holds any, else `("files", files())`."""
    with engine.connect() as db:
        held = stored(db)
    return ("database", held) if held != Policy() else ("files", files())


def held(url: str) -> Policy | None:
    """The policy the store at `url` holds; None when it holds none (absent, not yet migrated, or no active version), which leaves the board
    with no guard, profile cell or watch until the policy chain fills it. A SQLite file that does not exist is not created;
    any other database error propagates, so a board never starts unguarded on a fault."""
    target = make_url(url)
    if target.get_backend_name() == "sqlite" and target.database not in (None, ":memory:") and not Path(target.database).exists():
        return None
    engine = create_engine(url)
    try:
        with engine.connect() as db:
            inspector = inspect(db)
            found = stored(db) if inspector.has_table(versions.name) and inspector.has_table(active.name) else Policy()
    finally:
        engine.dispose()
    return found if found != Policy() else None
