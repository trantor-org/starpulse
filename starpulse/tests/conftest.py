"""Postgres for the integration tests, and the history store on each database.

Standalone, the Postgres server is a throwaway container when Docker or Podman is available. A host project that runs
these tests inside its own suite may already provide `pg_engine` from a pytest plugin on a container it shares;
trantor's workspace plugin `db.testing` does, and then none is started here.
"""

import importlib.util
import shutil
import sqlite3
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, event, text

from starpulse._internal.eventlog import event_log
from starpulse._internal.eventlog.history import HistoryStore
from starpulse.tests.machines import MACHINES
from starpulse.tests.mock_issuer import IMAGE, answers

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
    "starpulse_insights",
    "starpulse_step_summaries",
    "starpulse_cases",
    "starpulse_lane_intervals",
    "starpulse_lanes",
    "starpulse_source_instances",
    "starpulse_forward_instances",
)


@event.listens_for(Engine, "connect")
def _sqlite_without_sync(connection: object, _record: object) -> None:
    """No sync per commit on a test's SQLite file: it need not survive a crash, and each `CREATE TABLE` of a fixture's
    stores otherwise waits on the disk, seconds per test when runners share it."""
    if isinstance(connection, sqlite3.Connection):
        connection.execute("PRAGMA synchronous=OFF")


@pytest.fixture(scope="session", autouse=True)
def _event_log_without_sync() -> Iterator[None]:
    """The event log sets `synchronous=NORMAL` on each connection after the listener above, so wrap its pragmas to end
    on OFF in a test. Production keeps them: a test of them imports the original `_sqlite_pragmas` before this runs."""
    production = event_log._sqlite_pragmas

    def unsynced(dbapi_connection: Any, record: Any) -> None:
        production(dbapi_connection, record)
        dbapi_connection.execute("PRAGMA synchronous=OFF")

    event_log._sqlite_pragmas = unsynced
    yield
    event_log._sqlite_pragmas = production


#: Containers the run starts in the background as soon as collection shows a test needs one, so the first test to ask
#: for it finds it up (or waits only for what is left) and is not charged the whole start. Keyed by what they serve.
_WARM: dict[str, Future] = {}
#: One at a time: testcontainers starts its reaper container with the first container, and two threads racing to do
#: so collide on its name.
_STARTER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="warm")


def _container_skip_reason() -> str | None:
    """Why no container can start here, or None."""
    if not any(shutil.which(runtime) for runtime in ("docker", "podman")):
        return "the integration cases that need a container need Docker or Podman"
    # The hub dependency group; without it (the IC suite) these cases are skipped.
    if importlib.util.find_spec("testcontainers") is None or importlib.util.find_spec("psycopg") is None:
        return "the integration cases that need a container need the hub dependency group"
    return None


def _start_postgres() -> Any:  # pragma: no mutate block — container lifecycle
    from testcontainers.community.postgres import PostgresContainer  # noqa: PLC0415

    # The data directory in memory and no sync: a throwaway server need not survive a crash, and initdb's syncs
    # took seconds on a disk the runners share.
    return (
        PostgresContainer("postgres:17-alpine", driver="psycopg")
        .with_env("POSTGRES_INITDB_ARGS", "--no-sync")
        .with_tmpfs_mount("/var/lib/postgresql/data")
        .with_command("postgres -c fsync=off -c synchronous_commit=off -c full_page_writes=off")
        .start()
    )


def _start_issuer() -> tuple[Any, str]:  # pragma: no mutate block — container lifecycle
    from testcontainers.core.container import DockerContainer  # noqa: PLC0415

    container = DockerContainer(IMAGE).with_exposed_ports(8080).start()
    address = f"http://127.0.0.1:{container.get_exposed_port(8080)}/default"
    deadline = time.monotonic() + 60
    while not answers(f"{address}/.well-known/openid-configuration"):
        assert time.monotonic() < deadline, "the mock issuer never answered"
        time.sleep(0.5)
    return container, address


def _warm(name: str, start: Callable[[], Any]) -> Future:
    if name not in _WARM:
        _WARM[name] = _STARTER.submit(start)
    return _WARM[name]


def pytest_collection_finish(session: pytest.Session) -> None:  # pragma: no mutate block — container lifecycle
    if _container_skip_reason():
        return
    wanted = set()
    for item in session.items:
        params = getattr(getattr(item, "callspec", None), "params", {})
        if "pg_engine" in item.fixturenames or "postgres" in params.values():
            wanted.add("postgres")
        if "issuer" in item.fixturenames:
            wanted.add("issuer")
    if "postgres" in wanted and "db.testing" not in sys.modules:
        _warm("postgres", _start_postgres)
    if "issuer" in wanted:
        _warm("issuer", _start_issuer)


def pytest_sessionfinish(session: pytest.Session) -> None:  # pragma: no mutate block — container lifecycle
    for name, future in _WARM.items():
        if not future.cancel() and future.exception() is None:
            (future.result() if name == "postgres" else future.result()[0]).stop()
    _WARM.clear()


if "db.testing" not in sys.modules:

    @pytest.fixture(scope="session")
    def pg_engine() -> Iterator[Engine]:  # pragma: no mutate block — container lifecycle
        if reason := _container_skip_reason():
            pytest.skip(reason)
        container = _warm("postgres", _start_postgres).result()
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


@pytest.fixture(scope="session")
def issuer() -> str:  # pragma: no mutate block — container lifecycle
    """The address of a mock OpenID Connect issuer container, for the hub's sign-in cases."""
    if reason := _container_skip_reason():
        pytest.skip(reason)
    return _warm("issuer", _start_issuer).result()[1]
