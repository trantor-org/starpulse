"""Redis and Postgres for the integration tests, and the history store on each database.

Standalone, each server is a throwaway container (the `testcontainers` dev dependency, so Docker must run). A host
project that runs these tests inside its own suite may already provide `redis_client` and `pg_engine` from a pytest
plugin on containers it shares; trantor's workspace plugin `db.testing` does, and then none is started here.
"""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text

from starpulse.history import HistoryStore
from starpulse.tests.machines import MACHINES

#: StarPulse's own tables, dropped before each Postgres test so it starts empty.
_TABLES = ("starpulse_machine_events", "starpulse_lane_changes", "starpulse_learned_steps", "starpulse_gaps")

if "db.testing" not in sys.modules:

    @pytest.fixture(scope="session")
    def _redis_container() -> Iterator:  # pragma: no mutate block — container lifecycle
        from testcontainers.community.redis import RedisContainer  # noqa: PLC0415 - a unit run needs no Docker

        with RedisContainer("redis:8-alpine") as container:
            yield container

    @pytest.fixture
    def redis_client(_redis_container) -> Iterator:
        """A client on the container's Redis, flushed before the test so it starts empty."""
        client = _redis_container.get_client(decode_responses=True)
        client.flushdb()
        try:
            yield client
        finally:
            client.close()

    @pytest.fixture(scope="session")
    def pg_engine() -> Iterator[Engine]:  # pragma: no mutate block — container lifecycle
        from testcontainers.community.postgres import PostgresContainer  # noqa: PLC0415 - a unit run needs no Docker

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
