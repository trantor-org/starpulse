"""Opening the store does no maintenance: the schema, the lane repair and the summaries come from `starpulse migrate`."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.migrate import StoreNotMigrated, migrate
from starpulse.flow_metrics.history import HistoryStore


@pytest.mark.parametrize("step", ["repair_lanes", "rebuild_summaries", "build_summaries"])
def test_opening_a_migrated_store_runs_no_maintenance_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str) -> None:
    url = f"sqlite:///{tmp_path / 'history.sqlite'}"
    migrate(create_engine(url))

    def refuse(*_args: object) -> None:
        raise AssertionError(f"opening the store ran {step}")

    monkeypatch.setattr(HistoryStore, step, refuse)

    HistoryStore(url, {})


@pytest.mark.unmigrated
def test_opening_an_unmigrated_history_refuses_and_creates_no_table(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'history.sqlite'}"

    with pytest.raises(StoreNotMigrated, match="starpulse migrate"):
        HistoryStore(url, {})

    assert inspect(create_engine(url)).get_table_names() == []


@pytest.mark.unmigrated
def test_reading_an_unmigrated_event_log_refuses_and_creates_no_table(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'events.sqlite'}"

    with pytest.raises(StoreNotMigrated, match="starpulse migrate"):
        EventLog(url).engine

    assert inspect(create_engine(url)).get_table_names() == []
