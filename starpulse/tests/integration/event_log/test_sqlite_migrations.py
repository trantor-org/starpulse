"""A SQLite store is versioned by the Alembic chain: a fresh file is built by it, a store from before the chain is
stamped and upgraded, and nothing but the chain changes its schema."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text

from starpulse.event_log import migrate
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.migrate import alembic_config
from starpulse.event_log.readmodel import metadata as readmodel_metadata
from starpulse.event_log.store import metadata as store_metadata
from starpulse.event_log.tables import VERSION_TABLE, checkpoints, day_rollups, metadata
from starpulse.flow_metrics import history
from starpulse.flow_metrics.history import HistoryStore
from starpulse.tests.machines import MACHINES

_MIGRATIONS = Path(migrate.__file__).parent / "migrations"
#: Objects the metadata and the chain disagree on: the shelved hub's rollups table, which no revision creates, and the
#: lane-change index only the chain makes.
_SQLITE_ONLY_INDEX = "ix_starpulse_lane_changes_observed"
#: The index revision 0020 added to the declared schema, so the release before the chain had none.
_RETIRED_AT_INDEX = "ix_starpulse_retired_tasks_retired_at"
#: The table revision 0034 added, so the release before the chain had none.
_CLAIM_EXPIRIES = "starpulse_claim_expiries"
_DIALECT_ONLY = {day_rollups.name, _SQLITE_ONLY_INDEX}


def _head() -> str:
    return ScriptDirectory(str(_MIGRATIONS)).get_current_head()


def _versions(engine: Engine) -> list[str]:
    """The revisions the store records, none for a store the chain never touched."""
    if not inspect(engine).has_table(VERSION_TABLE):
        return []
    with engine.connect() as db:
        return list(db.execute(text(f"SELECT version_num FROM {VERSION_TABLE}")).scalars())


def _indexes(engine: Engine, table: str) -> set[str]:
    return {index["name"] for index in inspect(engine).get_indexes(table)}


def _a_pre_alembic_store(path: Path) -> Engine:
    """A store as the release before the chain left it: every table but the rollups, no version table."""
    engine = create_engine(f"sqlite:///{path}")
    tables = [
        table
        for table in metadata.sorted_tables
        if table not in (day_rollups, checkpoints) and table.name != _CLAIM_EXPIRIES
    ]
    metadata.create_all(engine, tables=tables)
    with engine.begin() as db:
        db.execute(text("CREATE TABLE starpulse_cursors (stream VARCHAR PRIMARY KEY, after_id INTEGER NOT NULL)"))
        db.execute(
            text(
                "CREATE TABLE starpulse_board_state "
                "(stream VARCHAR PRIMARY KEY, after_id VARCHAR NOT NULL, state JSON NOT NULL, saved_at FLOAT NOT NULL)"
            )
        )
        db.execute(text(f"DROP INDEX {_RETIRED_AT_INDEX}"))
        db.execute(text("DROP INDEX ix_starpulse_machine_events_run"))
    return engine


def test_the_chain_has_one_head() -> None:
    assert ScriptDirectory(str(_MIGRATIONS)).get_heads() == ["0034"]


def test_a_fresh_store_is_built_by_the_chain_and_matches_the_declared_schema(tmp_path: Path) -> None:
    store = HistoryStore(f"sqlite:///{tmp_path / 'fresh.sqlite'}", MACHINES)

    with store.engine.connect() as db:
        context = MigrationContext.configure(
            db,
            opts={
                "compare_type": True,
                "include_name": lambda name, kind, _: name != VERSION_TABLE,
                "include_object": lambda obj, name, kind, reflected, _: name not in _DIALECT_ONLY,
            },
        )
        drift = compare_metadata(context, [metadata, store_metadata, readmodel_metadata])

    assert (_versions(store.engine), drift) == ([_head()], [])


def test_a_fresh_stores_event_ids_are_never_handed_out_again(tmp_path: Path) -> None:
    store = HistoryStore(f"sqlite:///{tmp_path / 'fresh.sqlite'}", MACHINES)
    insert = "INSERT INTO starpulse_events (stream, event_id, fields, at) VALUES ('s', :event_id, '{}', 1)"

    with store.engine.begin() as db:
        db.execute(text(insert), {"event_id": "a"})
        db.execute(text(insert), {"event_id": "b"})
        db.execute(text("DELETE FROM starpulse_events WHERE event_id = 'b'"))
        db.execute(text(insert), {"event_id": "c"})
        ids = list(db.execute(text("SELECT id FROM starpulse_events ORDER BY id")).scalars())

    assert ids == [1, 3]


def test_a_store_from_before_the_chain_is_stamped_and_upgraded_with_its_rows_intact(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    legacy = _a_pre_alembic_store(path)
    with legacy.begin() as db:
        db.execute(
            text(
                "INSERT INTO starpulse_lane_changes (event_id, task, old_status, new_status, observed_at) "
                "VALUES ('lc-1', 'PROJ-7', 'Ready', 'In Progress', 100.0)"
            )
        )
        db.execute(text("INSERT INTO starpulse_cursors (stream, after_id) VALUES ('machine:events', 9)"))
    legacy.dispose()

    store = HistoryStore(f"sqlite:///{path}", MACHINES)

    with store.engine.connect() as db:
        changes = db.execute(text("SELECT event_id, task, observed_at FROM starpulse_lane_changes")).all()
    assert (
        _versions(store.engine),
        [tuple(row) for row in changes],
        store.checkpoints.load("machine:events")[0],
        _SQLITE_ONLY_INDEX in _indexes(store.engine, "starpulse_lane_changes"),
        _RETIRED_AT_INDEX in _indexes(store.engine, "starpulse_retired_tasks"),
    ) == ([_head()], [("lc-1", "PROJ-7", 100.0)], 9, True, True)


def test_the_checkpoint_revision_moves_cursors_and_saved_boards_into_one_table_and_drops_the_old_ones(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'before.sqlite'}")
    with engine.begin() as db:
        config = alembic_config(db)
        command.upgrade(config, "0024")
        db.execute(text("INSERT INTO starpulse_cursors (stream, after_id) VALUES ('machine:events', 9)"))
        db.execute(
            text(
                "INSERT INTO starpulse_board_state (stream, after_id, state, saved_at) "
                "VALUES ('board:tasks', '41-0', '{\"open\": {}}', 5.0)"
            )
        )
        command.upgrade(config, "0025")
        rows = db.execute(
            text("SELECT name, position, schema_version, state FROM starpulse_checkpoints ORDER BY name")
        ).all()
        tables = set(inspect(db).get_table_names())

    assert ([tuple(row) for row in rows], {"starpulse_cursors", "starpulse_board_state"} & tables) == (
        [("board:tasks", 41, 0, '{"open": {}}'), ("machine:events", 9, 0, None)],
        set(),
    )


def test_a_store_already_at_head_is_opened_again_unchanged(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'again.sqlite'}"
    HistoryStore(url, MACHINES).engine.dispose()

    again = HistoryStore(url, MACHINES)

    assert _versions(again.engine) == [_head()]


def test_the_event_log_and_the_history_store_opening_one_file_at_once_both_open_it(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'shared.sqlite'}"

    def open_it(kind: int) -> None:
        if kind % 2:
            HistoryStore(url, MACHINES)
        else:
            EventLog(url).engine.dispose()

    with ThreadPoolExecutor(max_workers=6) as pool:
        for opened in [pool.submit(open_it, kind) for kind in range(6)]:
            opened.result()

    assert _versions(create_engine(url)) == [_head()]
