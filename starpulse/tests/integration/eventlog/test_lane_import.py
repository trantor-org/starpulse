"""`starpulse import-history FILE`: a board's earlier lane changes enter the instance store once, in their own order."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from starpulse._internal.eventlog import lane_import
from starpulse._internal.eventlog.history import HistoryStore
from starpulse._internal.server import history_import
from starpulse.tests.machines import MACHINES

#: The change lines an exporter writes: one task's path, the earliest first, and a no-op move (Done to Done).
LINES = [
    {"event_id": "u-1", "task": "T-1", "lane": "Ready", "time": 100.0},
    {"event_id": "u-2", "task": "T-1", "lane": "In Progress", "time": 200.0},
    {"event_id": "u-3", "task": "T-1", "lane": "In Progress", "time": 250.0},
    {"event_id": "u-4", "task": "T-1", "lane": "Done", "time": 300.0},
    {"event_id": "u-5", "task": "T-2", "lane": "Ready", "time": 150.0},
]


def _store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(f"sqlite:///{tmp_path / 'store.sqlite'}", MACHINES)


def _rows(store: HistoryStore) -> list[tuple[str, str, str | None, str, float]]:
    with store.engine.connect() as db:
        query = "SELECT event_id, task, old_status, new_status, observed_at FROM starpulse_lane_changes ORDER BY observed_at"
        return [tuple(row) for row in db.execute(text(query))]


def _changes(lines: list[dict]) -> list[lane_import.Change]:
    return [lane_import.Change(d["event_id"], d["task"], d["lane"], d["time"]) for d in lines]


def test_importing_the_same_changes_twice_leaves_one_row_each_and_summaries_that_match_them(tmp_path: Path) -> None:
    store = _store(tmp_path)

    first = store.import_lanes(_changes(LINES))
    after_first = _rows(store)
    second = store.import_lanes(_changes(LINES))

    assert (first, second) == (4, 0)  # u-3 repeats the lane T-1 was in, so it is no move
    assert _rows(store) == after_first == [
        ("u-1", "T-1", None, "ready", 100.0),
        ("u-5", "T-2", None, "ready", 150.0),
        ("u-2", "T-1", "ready", "in_progress", 200.0),
        ("u-4", "T-1", "in_progress", "done", 300.0),
    ]
    assert store.summary_differences() == []


def test_changes_older_than_the_store_holds_chain_in_front_of_the_live_ones(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_lane("live-1", "T-1", "Review", 500.0)

    store.import_lanes(_changes(LINES))

    assert [(c["from"], c["to"]) for c in store.lane_path("T-1")] == [
        (None, "ready"),
        ("ready", "in_progress"),
        ("in_progress", "done"),
        ("done", "review"),
    ]
    assert store.summary_differences() == []


def test_a_move_the_store_holds_under_another_event_id_is_not_added_again(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_lane("T-1@ready@100.0", "T-1", "Ready", 100.0)

    imported = store.import_lanes(_changes(LINES[:1]))

    assert imported == 0
    assert len(_rows(store)) == 1


def test_a_line_that_is_not_a_change_names_its_line_number(tmp_path: Path) -> None:
    path = tmp_path / "lanes.jsonl"
    path.write_text(json.dumps(LINES[0]) + "\n" + json.dumps({"task": "T-1", "lane": "Done"}) + "\n")

    with pytest.raises(ValueError, match=r"lanes\.jsonl:2"):
        lane_import.read(path)


def test_the_command_imports_a_file_into_the_store_the_config_names_and_a_second_run_adds_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_file = tmp_path / "history.sqlite"
    config = tmp_path / "starpulse.toml"
    config.write_text(f'database_url = "sqlite:///{store_file}"\n')
    lines = tmp_path / "lanes.jsonl"
    lines.write_text("".join(json.dumps(line) + "\n" for line in LINES))
    argv = [str(lines), "--config", str(config)]

    assert history_import.main(argv) == 0
    first = json.loads(capsys.readouterr().out)
    assert history_import.main(argv) == 0
    second = json.loads(capsys.readouterr().out)

    assert (first["read"], first["imported"]) == (5, 4)
    assert (second["read"], second["imported"]) == (5, 0)
    assert second["summary_differences"] == []
    held = HistoryStore(f"sqlite:///{store_file}", MACHINES)
    assert [row[0] for row in _rows(held)] == ["u-1", "u-5", "u-2", "u-4"]


def test_a_file_with_a_line_that_is_not_a_change_exits_1_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_file = tmp_path / "history.sqlite"
    config = tmp_path / "starpulse.toml"
    config.write_text(f'database_url = "sqlite:///{store_file}"\n')
    lines = tmp_path / "lanes.jsonl"
    lines.write_text(json.dumps(LINES[0]) + "\nnot json\n")

    assert history_import.main([str(lines), "--config", str(config)]) == 1

    assert "lanes.jsonl:2" in capsys.readouterr().err
    assert not store_file.exists()
