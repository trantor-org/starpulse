"""The registry follows the definition files: the Board's machine and each file under `.starpulse/machines/`."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pytest
import yaml
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.store import EventStore, NewEvent
from starpulse.event_log.store.machine_registry import MachineRegistry, StrandedTasks
from starpulse.machine_engine.model.machine_definition import MachineDefinitionError
from starpulse.runtime.config import Config
from starpulse.runtime.machine_sync import sync_definitions

from tests.stores import migrate_config_store

BOARD = {
    "name": "board",
    "states": {"ready": {"initial": True}, "doing": {}, "done": {"final": True}},
    "events": {"start": [{"from": "ready", "to": "doing"}], "finish": [{"from": "doing", "to": "done"}]},
}
REVIEW = {
    "name": "review",
    "states": {"open": {"initial": True}, "closed": {"final": True}},
    "events": {"close": [{"from": "open", "to": "closed"}]},
}
RENAMED = BOARD | {
    "states": {"ready": {"initial": True}, "in_progress": {}, "done": {"final": True}},
    "events": {"start": [{"from": "ready", "to": "in_progress"}], "finish": [{"from": "in_progress", "to": "done"}]},
}


def _write(base: Path, relative: str, document: dict) -> None:
    path = base / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document))


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        tracker_url=None,
        mode="ic",
        runs=(),
        database_url=f"sqlite:///{tmp_path / 'events.sqlite'}",
        board={"machine": "board.yaml"},
    )


def _registry(config: Config) -> tuple[MachineRegistry, EventStore]:
    engine = EventLog(config.database_url).engine
    store = EventStore(engine)
    return MachineRegistry(engine, store), store


def test_the_board_machine_and_each_owners_definitions_directory_are_activated(tmp_path: Path, config: Config) -> None:
    _write(tmp_path, "board.yaml", BOARD)
    _write(tmp_path, ".starpulse/machines/review.yaml", REVIEW)

    hashes = sync_definitions(config, tmp_path)

    registry, _ = _registry(config)
    assert set(hashes) == {"board", "review"}
    assert registry.active_hash("board") == hashes["board"]
    assert registry.active_hash("review") == hashes["review"]


def test_a_second_sync_of_unchanged_files_changes_nothing(tmp_path: Path, config: Config) -> None:
    _write(tmp_path, "board.yaml", BOARD)

    assert sync_definitions(config, tmp_path) == sync_definitions(config, tmp_path)


def test_a_renamed_state_with_live_tasks_is_refused_naming_them(tmp_path: Path, config: Config) -> None:
    _write(tmp_path, "board.yaml", BOARD)
    first = sync_definitions(config, tmp_path)["board"]
    registry, store = _registry(config)
    registry.append(
        "task", "TASK-1", 0, [NewEvent("TaskCreated", {"title": "t", "state": "doing"}, "adin", "operator")]
    )

    _write(tmp_path, "board.yaml", RENAMED)
    with pytest.raises(MachineDefinitionError, match=r"doing.*TASK-1"):
        sync_definitions(config, tmp_path)

    assert registry.active_hash("board") == first


def test_a_task_that_only_archived_holds_no_state_and_does_not_block_a_dropped_state(
    tmp_path: Path, config: Config
) -> None:
    _write(tmp_path, "board.yaml", BOARD)
    sync_definitions(config, tmp_path)
    registry, store = _registry(config)
    store.append("task", "TASK-9", 0, [NewEvent("Archived", {}, "adin", "operator")])

    _write(tmp_path, "board.yaml", RENAMED)
    second = sync_definitions(config, tmp_path)["board"]

    assert registry.active_hash("board") == second


def test_a_renamed_state_with_a_mapping_remaps_the_live_tasks_on_reload(tmp_path: Path, config: Config) -> None:
    _write(tmp_path, "board.yaml", BOARD)
    sync_definitions(config, tmp_path)
    registry, store = _registry(config)
    registry.append(
        "task", "TASK-1", 0, [NewEvent("TaskCreated", {"title": "t", "state": "doing"}, "adin", "operator")]
    )

    _write(tmp_path, "board.yaml", RENAMED | {"migrations": {"doing": "in_progress"}})
    second = sync_definitions(config, tmp_path)["board"]

    assert registry.active_hash("board") == second
    assert replay(store.read("task", "TASK-1"))["state"] == "in_progress"


def test_serve_admits_the_definitions_its_config_names_and_refuses_a_stranding_edit(tmp_path: Path) -> None:
    from starpulse.runtime.server import admit_definitions  # noqa: PLC0415 - imports the server stack

    path = tmp_path / "starpulse.toml"
    path.write_text(f'database_url = "sqlite:///{tmp_path / "events.sqlite"}"\n[board]\nmachine = "board.yaml"\n')
    _write(tmp_path, "board.yaml", BOARD)
    migrate_config_store(path)
    args = argparse.Namespace(config=path)
    admit_definitions(args)
    registry, _ = _registry(
        Config(tracker_url=None, mode="ic", runs=(), database_url=f"sqlite:///{tmp_path / 'events.sqlite'}")
    )
    registry.append(
        "task", "TASK-1", 0, [NewEvent("TaskCreated", {"title": "t", "state": "doing"}, "adin", "operator")]
    )

    _write(tmp_path, "board.yaml", RENAMED)
    with pytest.raises(ValueError, match=r"doing.*TASK-1"):
        admit_definitions(args)


def _strand_task(tmp_path: Path, config: Config) -> str:
    """A live task in `doing` under BOARD, then the board file renamed so `doing` is gone; the hash left active."""
    _write(tmp_path, "board.yaml", BOARD)
    first = sync_definitions(config, tmp_path)["board"]
    registry, _ = _registry(config)
    registry.append(
        "task", "TASK-1", 0, [NewEvent("TaskCreated", {"title": "t", "state": "doing"}, "adin", "operator")]
    )
    _write(tmp_path, "board.yaml", RENAMED)
    return first


def test_stranded_tasks_still_let_the_other_definition_files_activate(tmp_path: Path, config: Config) -> None:
    first = _strand_task(tmp_path, config)
    _write(tmp_path, ".starpulse/machines/review.yaml", REVIEW)

    with pytest.raises(StrandedTasks, match=r"doing.*TASK-1"):
        sync_definitions(config, tmp_path)

    registry, _ = _registry(config)
    assert registry.active_hash("board") == first
    assert registry.active_hash("review") is not None


def _serve_args(tmp_path: Path) -> argparse.Namespace:
    path = tmp_path / "starpulse.toml"
    path.write_text(f'database_url = "sqlite:///{tmp_path / "events.sqlite"}"\n[board]\nmachine = "board.yaml"\n')
    migrate_config_store(path)
    return argparse.Namespace(config=path)


def test_serve_start_warns_naming_the_stranded_task_and_goes_on(
    tmp_path: Path, config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    from starpulse.runtime.server import admit_at_start  # noqa: PLC0415 - imports the server stack

    args = _serve_args(tmp_path)
    _strand_task(tmp_path, config)

    with caplog.at_level(logging.WARNING):
        admit_at_start(argparse.ArgumentParser(), args)

    assert any(r.levelno == logging.WARNING and "TASK-1" in r.getMessage() for r in caplog.records)


def test_a_reload_that_strands_a_task_is_still_refused(tmp_path: Path, config: Config) -> None:
    from starpulse.runtime.server import admit_definitions  # noqa: PLC0415 - imports the server stack

    args = _serve_args(tmp_path)
    _strand_task(tmp_path, config)

    with pytest.raises(ValueError, match=r"doing.*TASK-1"):
        admit_definitions(args)


def test_serve_start_still_exits_on_a_definition_the_registry_refuses_for_another_reason(tmp_path: Path) -> None:
    from starpulse.runtime.server import admit_at_start  # noqa: PLC0415 - imports the server stack

    args = _serve_args(tmp_path)
    _write(tmp_path, "board.yaml", {"name": "board", "states": {}, "events": {}})

    with pytest.raises(SystemExit) as raised:
        admit_at_start(argparse.ArgumentParser(), args)

    assert raised.value.code == 1
