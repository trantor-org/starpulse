"""The machine registry: definitions versioned by hash, State changes applied only with a mapping, as one transaction."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.store import EventStore, NewEvent, StaleVersion
from starpulse.event_log.store.machine_registry import LiveTask, MachineRegistry
from starpulse.machine_engine.model.machine_definition import MachineDefinitionError

BOARD: dict[str, Any] = {
    "name": "board",
    "states": {"ready": {"initial": True}, "doing": {}, "done": {"final": True}},
    "events": {
        "start": [{"from": "ready", "to": "doing"}],
        "finish": [{"from": "doing", "to": "done"}],
    },
}


def _renamed(**extra: Any) -> dict[str, Any]:
    """BOARD with `doing` renamed `in_progress`."""
    document = copy.deepcopy(BOARD)
    document["states"] = {"ready": {"initial": True}, "in_progress": {}, "done": {"final": True}}
    document["events"] = {
        "start": [{"from": "ready", "to": "in_progress"}],
        "finish": [{"from": "in_progress", "to": "done"}],
    }
    return document | extra


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").engine


@pytest.fixture
def store(engine: Engine) -> EventStore:
    return EventStore(engine)


@pytest.fixture
def registry(engine: Engine, store: EventStore) -> MachineRegistry:
    return MachineRegistry(engine, store)


def _task(store: EventStore, registry: MachineRegistry, task: str, state: str) -> LiveTask:
    """A Task created in `state` under the active definition."""
    events = registry.append(
        "task", task, 0, [NewEvent("TaskCreated", {"title": task, "state": state}, "adin", "operator")]
    )
    return LiveTask(task, state, events[-1].version)


def test_a_rename_with_a_mapping_remaps_the_live_tasks(store: EventStore, registry: MachineRegistry) -> None:
    first = registry.activate(BOARD, [])
    live = [_task(store, registry, "TASK-1", "doing"), _task(store, registry, "TASK-2", "ready")]

    second = registry.activate(_renamed(migrations={"doing": "in_progress"}), live)

    assert second != first and registry.active_hash("board") == second
    assert replay(store.read("task", "TASK-1"))["state"] == "in_progress"
    assert replay(store.read("task", "TASK-2"))["state"] == "ready"
    assert [e.type for e in store.read("task", "TASK-1")] == ["TaskCreated", "Remapped"]
    assert store.read("task", "TASK-1")[-1].definition_hash == second
    assert store.head("task", "TASK-2") == 1


def test_a_rename_without_a_mapping_is_refused_naming_states_and_tasks(
    store: EventStore, registry: MachineRegistry
) -> None:
    first = registry.activate(BOARD, [])
    live = [_task(store, registry, "TASK-1", "doing")]

    with pytest.raises(MachineDefinitionError, match=r"doing.*TASK-1"):
        registry.activate(_renamed(), live)

    assert registry.active_hash("board") == first
    assert store.head("task", "TASK-1") == 1


def test_a_remap_that_meets_a_concurrent_append_rolls_back_whole(store: EventStore, registry: MachineRegistry) -> None:
    first = registry.activate(BOARD, [])
    live = [_task(store, registry, "TASK-1", "doing"), _task(store, registry, "TASK-2", "doing")]
    store.append("task", "TASK-2", 1, [NewEvent("CommentAdded", {"text": "late"}, "adin", "operator")])

    with pytest.raises(StaleVersion):
        registry.activate(_renamed(migrations={"doing": "in_progress"}), live)

    assert registry.active_hash("board") == first
    assert store.head("task", "TASK-1") == 1
    assert store.head("task", "TASK-2") == 2


def test_a_field_edit_carries_the_active_hash(store: EventStore, registry: MachineRegistry) -> None:
    active = registry.activate(BOARD, [])
    _task(store, registry, "TASK-1", "ready")

    edited = registry.append(
        "task", "TASK-1", 1, [NewEvent("FieldsEdited", {"changes": {"title": "x"}}, "adin", "operator")]
    )

    assert [e.definition_hash for e in edited] == [active]


def test_a_command_to_a_state_the_active_version_lacks_is_refused(store: EventStore, registry: MachineRegistry) -> None:
    registry.activate(BOARD, [])
    _task(store, registry, "TASK-1", "ready")

    with pytest.raises(MachineDefinitionError, match="in_progress"):
        registry.append("task", "TASK-1", 1, [NewEvent("Transitioned", {"to": "in_progress"}, "adin", "operator")])


def test_a_replay_across_the_change_reads_each_event_under_its_own_hash(
    store: EventStore, registry: MachineRegistry
) -> None:
    first = registry.activate(BOARD, [])
    live = [_task(store, registry, "TASK-1", "doing")]
    second = registry.activate(_renamed(migrations={"doing": "in_progress"}), live)

    events = store.read("task", "TASK-1")

    assert [e.definition_hash for e in events] == [first, second]
    assert "doing" in registry.definition(events[0].definition_hash)["states"]
    assert "in_progress" in registry.definition(events[1].definition_hash)["states"]


def test_a_mapping_is_part_of_the_hash(registry: MachineRegistry) -> None:
    registry.activate(BOARD, [])

    with_mapping = registry.activate(_renamed(migrations={"doing": "in_progress"}), [])
    without = registry.activate(_renamed(), [])

    assert with_mapping != without


def test_reactivating_the_same_definition_is_a_no_op(store: EventStore, registry: MachineRegistry) -> None:
    active = registry.activate(BOARD, [])
    live = [_task(store, registry, "TASK-1", "doing")]

    assert registry.activate(copy.deepcopy(BOARD), live) == active
    assert store.head("task", "TASK-1") == 1


def test_a_split_that_no_mapping_expresses_is_refused(store: EventStore, registry: MachineRegistry) -> None:
    first = registry.activate(BOARD, [])
    live = [_task(store, registry, "TASK-1", "doing")]
    split = _renamed()
    split["states"] = {"ready": {"initial": True}, "coding": {}, "testing": {}, "done": {"final": True}}
    split["events"] = {
        "start": [{"from": "ready", "to": "coding"}],
        "review": [{"from": "coding", "to": "testing"}],
        "finish": [{"from": "testing", "to": "done"}],
    }

    with pytest.raises(MachineDefinitionError, match="doing"):
        registry.activate(split, live)
    with pytest.raises(MachineDefinitionError, match="doing -> nowhere"):
        registry.activate(split | {"migrations": {"doing": "nowhere"}}, live)

    assert registry.active_hash("board") == first


def test_reactivating_the_active_definition_ignores_live_states_it_lacks(registry: MachineRegistry) -> None:
    active = registry.activate(BOARD, [])
    stranded = [LiveTask("TASK-1", "Done", 1), LiveTask("TASK-2", "", 1)]

    assert registry.activate(copy.deepcopy(BOARD), stranded) == active


def test_a_changed_definition_activates_over_live_tasks_held_in_display_names(
    store: EventStore, registry: MachineRegistry
) -> None:
    registry.activate(BOARD, [])
    live: list[LiveTask] = []
    for task, status in (("TASK-1", "In Progress"), ("TASK-2", "Doing")):
        events = store.append(
            "task", task, 0, [NewEvent("TaskImported", {"title": task, "state": status}, "adin", "operator")]
        )
        live.append(LiveTask(task, status, events[-1].version))

    second = registry.activate(_renamed(migrations={"doing": "in_progress"}), live)

    assert registry.active_hash("board") == second
    assert [e.type for e in store.read("task", "TASK-1")] == ["TaskImported"]
    assert [e.type for e in store.read("task", "TASK-2")] == ["TaskImported", "Remapped"]
    assert replay(store.read("task", "TASK-2"))["state"] == "in_progress"


def test_an_archived_task_in_a_dropped_state_neither_blocks_nor_is_remapped(
    store: EventStore, registry: MachineRegistry
) -> None:
    registry.activate(BOARD, [])
    held = _task(store, registry, "TASK-1", "doing")
    archived = LiveTask(held.id, held.state, held.version, archived=True)
    document = _renamed()

    registry.activate(document, [archived])

    assert registry.active_hash("board") is not None
    assert [e.type for e in store.read("task", "TASK-1")] == ["TaskCreated"]
