"""The history store and event-log database each test starts from: an empty SQLite file."""

import shutil
import sqlite3
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, event

from starpulse.board.adapters import upstream_backlog
from starpulse.event_log import event_log
from starpulse.flow_metrics.history import HistoryStore
from starpulse.tests.machines import MACHINES


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


@pytest.fixture(scope="session")
def _sqlite_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A SQLite store the migration chain built once on this worker, at its head."""
    path = tmp_path_factory.mktemp("template") / "store.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    event_log.migrate(engine)
    engine.dispose()
    return path


@pytest.fixture(scope="module")
def sqlite_stores_from_template(_sqlite_template: Path) -> Iterator[None]:
    """Each new SQLite store a module's tests open starts as a copy of the template, which the chain then finds at its
    head: the chain's upgrade of an empty file is a fifth of a second, paid by each store of each test otherwise."""
    production = event_log.migrate
    copying = threading.Lock()

    def from_template(engine: Engine) -> None:
        database = engine.url.database
        with copying:
            if engine.dialect.name == "sqlite" and database and database != ":memory:" and not Path(database).exists():
                shutil.copyfile(_sqlite_template, database)
        production(engine)

    event_log.migrate = from_template
    yield
    event_log.migrate = production


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    """An empty history store on a SQLite file."""
    return HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """The URL of an empty SQLite database for the event log."""
    return f"sqlite:///{tmp_path / 'events.sqlite'}"


def stop_upstream_backlogs(timeout: float = 5.0) -> None:
    """Stop every running upstream Backlog adapter thread and wait for each to end."""
    for backlog, thread in list(upstream_backlog._live.items()):
        backlog.stop()
        thread.join(timeout)


@pytest.fixture(autouse=True)
def _no_upstream_backlog_thread_outlives_its_test() -> Iterator[None]:
    """A server started over an upstream Backlog project polls it on a thread with no owner; end each one the test
    left, so it cannot allocate during a later test on the same worker."""
    yield
    stop_upstream_backlogs()
    leaked = [t for t in threading.enumerate() if t.name == "upstream-backlog"]
    assert not leaked, "an upstream-backlog thread outlived its test"


@pytest.fixture(autouse=True)
def _sqlite_engines_close_with_their_test() -> Iterator[None]:
    """Dispose every SQLite engine the test connected through: an `EventLog` or `HistoryStore` it built is never closed
    by the code under test, and its pooled connections hold three descriptors each until the worker process ends."""
    used: list[Engine] = []

    def note(connection: Any) -> None:
        if connection.engine.dialect.name == "sqlite" and connection.engine not in used:
            used.append(connection.engine)

    event.listen(Engine, "engine_connect", note)
    yield
    event.remove(Engine, "engine_connect", note)
    for engine in used:
        engine.dispose()


class FakeSupervisor:
    """What an in-process `server.main` supervises with: records its commands and starts no child process."""

    made: list[FakeSupervisor] = []

    def __init__(self, commands: dict[str, list[str]], **options: object) -> None:
        self.commands = commands
        self.options = options
        self.started = False
        self.stopped = False
        type(self).made.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class FakeForker:
    """What an in-process `server.main` forks workers with: records what it was built for and starts no process."""

    made: list[FakeForker] = []

    def __init__(self, modules: list[str], listening: object = None) -> None:
        self.modules = modules
        self.listening = listening
        self.started = False
        self.closed = False
        type(self).made.append(self)

    def start(self, *, forked: bool = False) -> None:
        self.started = True
        self.forked = forked

    def retire(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def supervisors(monkeypatch: pytest.MonkeyPatch) -> list[FakeSupervisor]:
    """The supervisors an in-process `server.main` built this test: none of them starts a real worker child or
    preloaded process (`forkers` holds the latter)."""
    FakeSupervisor.made = []
    monkeypatch.setenv("STARPULSE_STATIC", "")  # `server.main` exports the page build it checked; undone at teardown
    monkeypatch.delenv("STARPULSE_STATIC")
    FakeForker.made = []
    if "starpulse.runtime.server" in sys.modules:
        monkeypatch.setattr("starpulse.runtime.server.Supervisor", FakeSupervisor)
        monkeypatch.setattr("starpulse.runtime.server.Forker", FakeForker)
    return FakeSupervisor.made


@pytest.fixture
def forkers() -> list[FakeForker]:
    return FakeForker.made
