"""Postgres for the integration tests, and the history store on each database.

Standalone, the Postgres server is a throwaway container when Docker or Podman is available. A host project that runs
these tests inside its own suite may already provide `pg_engine` from a pytest plugin on a container it shares;
trantor's workspace plugin `db.testing` does, and then none is started here.
"""

import shutil
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text

from starpulse.history import HistoryStore
from starpulse.tests.machines import MACHINES

#: StarPulse's own tables, dropped before each Postgres test so it starts empty.
_TABLES = (
    "starpulse_machine_events",
    "starpulse_lane_changes",
    "starpulse_learned_steps",
    "starpulse_gaps",
    "starpulse_events",
    "starpulse_cursors",
    "starpulse_board_state",
    "starpulse_day_rollups",
)

if "db.testing" not in sys.modules:

    @pytest.fixture(scope="session")
    def pg_engine() -> Iterator[Engine]:  # pragma: no mutate block — container lifecycle
        if not any(shutil.which(runtime) for runtime in ("docker", "podman")):
            pytest.skip("Postgres integration cases need Docker or Podman")
        # The hub dependency group; without it (the IC suite) the Postgres cases are skipped.
        pytest.importorskip("psycopg", reason="Postgres integration cases need the hub extras")
        postgres = pytest.importorskip("testcontainers.community.postgres", reason="needs the hub dependency group")
        PostgresContainer = postgres.PostgresContainer  # noqa: N806

        with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
            engine = create_engine(container.get_connection_url())
            try:
                yield engine
            finally:
                engine.dispose()


@pytest.fixture(params=["sqlite", "postgres"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> HistoryStore:
    """An empty history store: a SQLite file, or StarPulse's tables on a Postgres server."""
    if request.param == "sqlite":
        return HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)
    engine: Engine = request.getfixturevalue("pg_engine")
    with engine.begin() as db:
        db.execute(text(f"DROP TABLE IF EXISTS {', '.join(_TABLES)}"))
    return HistoryStore(engine.url.render_as_string(hide_password=False), MACHINES, engine=engine)


@pytest.fixture(params=["sqlite", "postgres"])
def database_url(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    """The URL of an empty database for the event log: a SQLite file, or a Postgres server with StarPulse's tables dropped."""
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'events.sqlite'}"
    engine: Engine = request.getfixturevalue("pg_engine")
    with engine.begin() as db:
        db.execute(text(f"DROP TABLE IF EXISTS {', '.join(_TABLES)}"))
    return engine.url.render_as_string(hide_password=False)


@pytest.fixture
def empty_database(pg_engine: Engine) -> Iterator[Engine]:
    """A newly created Postgres database with no table in it."""
    name = f"hub_{uuid.uuid4().hex[:12]}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as db:
        db.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(pg_engine.url.set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as db:
            db.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
