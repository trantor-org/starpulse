"""The hub's history schema is versioned with the package: an empty Postgres database upgrades to head, and head is
the schema the code writes."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect, text

pytest.importorskip("alembic", reason="the hub extras are not installed")

from alembic import command  # noqa: E402
from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.runtime.migration import MigrationContext  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

from starpulse import hub  # noqa: E402
from starpulse.store import history  # noqa: E402, F401 - history declares its tables on the shared metadata
from starpulse.store.tables import metadata  # noqa: E402


def _url(engine: Engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def _head() -> str:
    script = ScriptDirectory(str(Path(hub.__file__).parent / "store" / "migrations"))
    return script.get_current_head()


def test_an_empty_database_upgrades_to_head_with_every_table(empty_database: Engine) -> None:
    hub.prepare(_url(empty_database))

    with empty_database.connect() as db:
        assert db.execute(text("SELECT version_num FROM starpulse_alembic_version")).scalars().all() == [_head()]
    assert set(metadata.tables) <= set(inspect(empty_database).get_table_names())


def _declared_by_the_hub_alone(obj: object, name: str | None, kind: str, reflected: bool, _: object) -> bool:
    """False for the one constraint the hub's partitioned `starpulse_events` keys differently from the shared metadata:
    Postgres needs `at` in it, and SQLite's event log, which shares the metadata, partitions nothing."""
    return not (
        kind == "unique_constraint" and getattr(getattr(obj, "table", None), "name", None) == "starpulse_events"
    )


def test_head_is_the_schema_the_code_declares(empty_database: Engine) -> None:
    hub.prepare(_url(empty_database))

    with empty_database.connect() as db:
        context = MigrationContext.configure(
            db,
            opts={
                "compare_type": True,
                "include_name": lambda name, kind, _: name != hub.VERSION_TABLE,
                "include_object": _declared_by_the_hub_alone,
            },
        )
        assert compare_metadata(context, metadata) == []
        unique = db.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'starpulse_events'::regclass AND contype = 'u'"
            )
        ).scalars()
        assert list(unique) == ["UNIQUE (event_id, at)"]


def test_preparing_a_database_already_at_head_changes_nothing(empty_database: Engine) -> None:
    hub.prepare(_url(empty_database))
    hub.prepare(_url(empty_database))

    with empty_database.connect() as db:
        assert db.execute(text("SELECT count(*) FROM starpulse_alembic_version")).scalar() == 1


def test_events_a_hub_already_holds_survive_the_move_into_partitions(empty_database: Engine) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(hub.__file__).parent / "store" / "migrations"))
    with empty_database.begin() as db:
        config.attributes["connection"] = db
        command.upgrade(config, "0001")
        for event_id, at in (("early", 1790000000.0), ("late", 1790000000.0 + 2 * 86400)):  # 2026-09-21 and -23 UTC
            db.execute(
                text("INSERT INTO starpulse_events (stream, event_id, fields, at) VALUES ('s', :e, '{}', :at)"),
                {"e": event_id, "at": at},
            )

    hub.prepare(_url(empty_database))

    hub.ensure_partitions(empty_database, today=date(2026, 9, 24), ahead=0)
    with empty_database.begin() as db:
        rows = db.execute(text("SELECT id, event_id, tableoid::regclass::text FROM starpulse_events ORDER BY id")).all()
        assert [tuple(r) for r in rows] == [
            (1, "early", "starpulse_events_20260921"),
            (2, "late", "starpulse_events_20260923"),
        ]
        new = db.execute(
            text(
                "INSERT INTO starpulse_events (stream, event_id, fields, at) VALUES ('s', 'new', '{}', 1790208000) RETURNING id"
            )
        ).scalar_one()
    assert new == 3


def test_the_summaries_revision_adds_its_tables_and_a_downgrade_drops_them(empty_database: Engine) -> None:
    summaries = {"starpulse_step_summaries", "starpulse_cases", "starpulse_lane_intervals"}
    config = Config()
    config.set_main_option("script_location", str(Path(hub.__file__).parent / "store" / "migrations"))
    with empty_database.begin() as db:
        config.attributes["connection"] = db
        command.upgrade(config, "0004")
        assert not summaries & set(inspect(db).get_table_names())
        command.upgrade(config, "0005")
        assert summaries <= set(inspect(db).get_table_names())
        assert {i["name"] for i in inspect(db).get_indexes("starpulse_lane_intervals")} >= {
            "ix_starpulse_lane_intervals_task",
            "ix_starpulse_lane_intervals_entered",
            "ix_starpulse_lane_intervals_left",
        }
        command.downgrade(config, "0004")
        assert not summaries & set(inspect(db).get_table_names())


def test_the_lane_counts_revision_counts_the_lanes_the_intervals_hold_and_a_downgrade_drops_it(
    empty_database: Engine,
) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(hub.__file__).parent / "store" / "migrations"))
    with empty_database.begin() as db:
        config.attributes["connection"] = db
        command.upgrade(config, "0005")
        db.execute(
            text(
                "INSERT INTO starpulse_lane_intervals (task, lane, entered_at, left_at, event_id) VALUES "
                "('A', 'Ready', 1, 2, 'a/e1'), ('A', 'Done', 2, NULL, 'a/e2'), ('B', 'Done', 3, NULL, 'b/e3'), "
                "('C', 'Ready', 4, NULL, 'e4')"
            )
        )
        command.upgrade(config, "0007")
        assert {
            (source, lane): (open_tasks, first_at)
            for source, lane, open_tasks, first_at in db.execute(
                text("SELECT source, lane, open_tasks, first_at FROM starpulse_lanes")
            )
        } == {("a", "Ready"): (0, 1), ("a", "Done"): (1, 2), ("b", "Done"): (1, 3), ("unattributed", "Ready"): (1, 4)}
        assert "ix_starpulse_lane_intervals_lane" in {
            i["name"] for i in inspect(db).get_indexes("starpulse_lane_intervals")
        }
        assert "ix_starpulse_cases_state" in {i["name"] for i in inspect(db).get_indexes("starpulse_cases")}
        command.downgrade(config, "0006")
        assert "starpulse_lanes" not in inspect(db).get_table_names()
        assert "ix_starpulse_lane_intervals_lane" not in {
            i["name"] for i in inspect(db).get_indexes("starpulse_lane_intervals")
        }
        assert "ix_starpulse_cases_state" not in {i["name"] for i in inspect(db).get_indexes("starpulse_cases")}
