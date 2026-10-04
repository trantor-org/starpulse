"""The adapter kit fails an adapter that breaks a contract, and passes one that keeps it."""

import re
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from starpulse.adapter_kit import BoardAdapterKit, MachineEventsAdapterKit, RunsAdapterKit, _AdapterKit
from starpulse.contracts import TaskKeys
from starpulse.tests.machines import MACHINES

PROJ = TaskKeys(key=re.compile(r"PROJ-\d+"), branch=re.compile(r"feature/(PROJ-\d+)"))
BRANCHES = {"feature/PROJ-1": "PROJ-1", "main": None}
TASK = {"id": "PROJ-1", "title": "t", "lane": "in_progress"}
EVENT = {"machine": "in-progress", "event": "WORKTREE_READY", "task": "PROJ-1", "time": "100.0"}
STEP = {"name": "a", "depends": [], "status": "succeeded", "kind": None}
DAG = {"name": "d", "status": "succeeded", "runId": "r", "startedAt": "", "finishedAt": "", "steps": [STEP]}


def adapter(kit: type[_AdapterKit], records: list[dict], **overrides: object) -> _AdapterKit:
    """An adapter of `kit`'s contract producing `records` on the fixture machines, its keys PROJ and its branch examples valid unless overridden."""
    attrs = {"keys": PROJ, "branches": BRANCHES, "machines": MACHINES, "produce": lambda self: records, **overrides}
    return type("Adapter", (kit,), attrs)()


def failing(check: Callable[[], None]) -> bool:
    try:
        check()
    except AssertionError, ValidationError:
        return True
    return False


def every_check(adapter: _AdapterKit) -> list[Callable[[], None]]:
    return [getattr(adapter, name) for name in dir(adapter) if name.startswith("test_")]


@pytest.mark.parametrize(
    ("kit", "records"),
    [(BoardAdapterKit, [TASK]), (MachineEventsAdapterKit, [EVENT]), (RunsAdapterKit, [DAG])],
)
def test_an_adapter_that_keeps_its_contract_passes_every_check(kit: type[_AdapterKit], records: list[dict]) -> None:
    assert [failing(check) for check in every_check(adapter(kit, records))] == [False] * len(
        every_check(adapter(kit, records))
    )


@pytest.mark.parametrize(
    ("kit", "records", "what"),
    [
        (BoardAdapterKit, [], "no records"),
        (BoardAdapterKit, [{**TASK, "title": None}], "a record the contract rejects"),
        (BoardAdapterKit, [{**TASK, "id": "OPS-1"}], "a key outside the declared scheme"),
        (BoardAdapterKit, [{**TASK, "lane": "no_such_lane"}], "a lane the Board machine lacks"),
        (MachineEventsAdapterKit, [{**EVENT, "task": "OPS-1"}], "a key outside the declared scheme"),
        (MachineEventsAdapterKit, [{**EVENT, "machine": "nope"}], "a machine the view does not draw"),
        (MachineEventsAdapterKit, [{**EVENT, "event": "NOPE"}], "an event the machine lacks"),
        (MachineEventsAdapterKit, [{**EVENT, "run": "r1"}], "an event keyed by both task and run"),
        (RunsAdapterKit, [{**DAG, "steps": [{**STEP, "depends": ["ghost"]}]}], "a step waiting on a ghost"),
        (RunsAdapterKit, [{**DAG, "steps": [STEP, STEP]}], "two steps of one name"),
        (RunsAdapterKit, [{**DAG, "status": "partially_succeeded"}], "a DAG status outside the enum"),
        (
            RunsAdapterKit,
            [{**DAG, "steps": [{**STEP, "status": "partially_succeeded"}]}],
            "a step status outside the enum",
        ),
    ],
)
def test_an_adapter_that_breaks_its_contract_fails_a_check(
    kit: type[_AdapterKit], records: list[dict], what: str
) -> None:
    checks = every_check(adapter(kit, records))

    assert any(failing(check) for check in checks), what


def test_an_adapter_whose_branch_examples_disagree_with_its_keys_fails() -> None:
    wrong = adapter(BoardAdapterKit, [TASK], branches={"feature/PROJ-1": "PROJ-2", "main": None})

    assert failing(wrong.test_the_branch_examples_map_to_the_task_keys_they_declare)


@pytest.mark.parametrize(
    "branches",
    [{}, {"feature/PROJ-1": "PROJ-1"}, {"main": None}],
    ids=["no examples", "only a task branch", "only a branch naming no task"],
)
def test_an_adapter_must_declare_a_branch_that_names_a_task_and_one_that_names_none(
    branches: dict[str, str | None],
) -> None:
    undeclared = adapter(BoardAdapterKit, [TASK], branches=branches)

    with pytest.raises(AssertionError) as raised:
        undeclared.test_the_branch_examples_map_to_the_task_keys_they_declare()

    assert str(raised.value).startswith("declare a branch that names a task and one that names none")


def test_an_adapter_with_no_records_is_told_nothing_is_checked() -> None:
    with pytest.raises(AssertionError) as raised:
        adapter(BoardAdapterKit, []).test_the_adapter_produces_records()

    assert str(raised.value).startswith("the adapter produced no records, so nothing is checked")


def test_an_adapter_that_does_not_override_produce_is_told_to() -> None:
    with pytest.raises(NotImplementedError) as raised:
        _AdapterKit().produce()

    assert str(raised.value) == "override produce() to return the adapter's records"


def test_the_placement_check_alone_fails_a_record_the_view_drops_for_its_key() -> None:
    board = adapter(BoardAdapterKit, [{**TASK, "id": "OPS-1"}])
    machine = adapter(MachineEventsAdapterKit, [{**EVENT, "task": "OPS-1"}])

    assert failing(getattr(board, "test_the_flow_view_places_every_task_in_its_lane_or_as_settled"))
    assert failing(getattr(machine, "test_the_flow_view_places_every_task_an_event_moved"))


@pytest.mark.parametrize("status", ["not_started", "queued", "running", "succeeded", "failed", "aborted", "skipped"])
def test_every_status_of_the_closed_enum_passes_the_runs_checks_with_or_without_the_raw_engine_status(
    status: str,
) -> None:
    records = [
        {**DAG, "status": status, "steps": [{**STEP, "status": status}]},
        {**DAG, "status": status, "raw": "engine_label", "steps": [{**STEP, "status": status, "raw": "engine_label"}]},
    ]

    assert [failing(check) for check in every_check(adapter(RunsAdapterKit, records))] == [False] * len(
        every_check(adapter(RunsAdapterKit, records))
    )
