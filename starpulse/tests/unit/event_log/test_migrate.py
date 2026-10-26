"""A fresh store is built from a per-process template of the chain's head; a store that holds tables still runs the chain."""

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text

from starpulse.event_log import migrate as migrate_module
from starpulse.event_log.migrate import alembic_config, migrate
from starpulse.event_log.tables import VERSION_TABLE


def schema(engine: Engine) -> tuple[list[tuple], str]:
    """The store's `sqlite_master` rows and its recorded revision."""
    with engine.connect() as db:
        rows = db.execute(text("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name")).all()
        return [tuple(row) for row in rows], db.execute(text(f"SELECT version_num FROM {VERSION_TABLE}")).scalar_one()


def chain_built() -> Engine:
    engine = create_engine("sqlite://")
    with engine.connect() as db:
        command.upgrade(alembic_config(db), "head")
        db.commit()
    return engine


@pytest.fixture
def upgrades(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The revisions the chain is run to while the test runs."""
    seen: list[str] = []
    upgrade = command.upgrade

    def counted(config, revision: str) -> None:
        seen.append(revision)
        upgrade(config, revision)

    monkeypatch.setattr(migrate_module.command, "upgrade", counted)
    return seen


def test_a_store_built_from_the_template_matches_one_the_chain_built() -> None:
    migrate(create_engine("sqlite://"))
    fresh = create_engine("sqlite://")

    migrate(fresh)

    assert schema(fresh) == schema(chain_built())


def test_a_fresh_store_does_not_run_the_chain_once_the_template_is_built(upgrades: list[str]) -> None:
    migrate(create_engine("sqlite://"))
    upgrades.clear()

    migrate(create_engine("sqlite://"))

    assert upgrades == []


def test_a_store_behind_the_head_still_runs_the_chain(upgrades: list[str]) -> None:
    engine = create_engine("sqlite://")
    with engine.connect() as db:
        command.upgrade(alembic_config(db), "0030")
        db.commit()
    upgrades.clear()

    migrate(engine)

    assert upgrades == ["head"]
    assert schema(engine) == schema(chain_built())
