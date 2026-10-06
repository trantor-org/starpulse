"""The hub's history schema is versioned with the package: an empty Postgres database upgrades to head, and head is
the schema the code writes."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, inspect, text

pytest.importorskip("alembic", reason="the hub extras are not installed")

from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.runtime.migration import MigrationContext  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

from starpulse import history, hub  # noqa: E402, F401 - history declares its tables on the shared metadata
from starpulse.tables import metadata  # noqa: E402


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


def _url(engine: Engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def _head() -> str:
    script = ScriptDirectory(str(Path(hub.__file__).parent / "migrations"))
    return script.get_current_head()


def test_an_empty_database_upgrades_to_head_with_every_table(empty_database: Engine) -> None:
    hub.prepare(_url(empty_database))

    with empty_database.connect() as db:
        assert db.execute(text("SELECT version_num FROM starpulse_alembic_version")).scalars().all() == [_head()]
    assert set(metadata.tables) <= set(inspect(empty_database).get_table_names())


def test_head_is_the_schema_the_code_declares(empty_database: Engine) -> None:
    hub.prepare(_url(empty_database))

    with empty_database.connect() as db:
        context = MigrationContext.configure(
            db,
            opts={"compare_type": True, "include_name": lambda name, kind, _: name != hub.VERSION_TABLE},
        )
        assert compare_metadata(context, metadata) == []


def test_preparing_a_database_already_at_head_changes_nothing(empty_database: Engine) -> None:
    hub.prepare(_url(empty_database))
    hub.prepare(_url(empty_database))

    with empty_database.connect() as db:
        assert db.execute(text("SELECT count(*) FROM starpulse_alembic_version")).scalar() == 1
