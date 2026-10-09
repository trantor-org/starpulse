"""The adapter kit fails an adapter that breaks a contract, and passes one that keeps it."""

import re
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from starpulse._internal.adapters.boards.seam import Written
from starpulse._internal.api.adapter_kit import BoardAdapterKit, MachineEventsAdapterKit, RunsAdapterKit, _AdapterKit
from starpulse.contracts.adapters import TaskKeys
from starpulse.tests.machines import MACHINES

PROJ = TaskKeys(key=re.compile(r"PROJ-\d+"), branch=re.compile(r"feature/(PROJ-\d+)"))
BRANCHES = {"feature/PROJ-1": "PROJ-1", "main": None}
TASK = {"id": "PROJ-1", "title": "t", "team": "PROJ", "lane": "in_progress"}
TEAMS = {"PROJ-1": "PROJ"}
EVENT = {"machine": "in-progress", "event": "WORKTREE_READY", "task": "PROJ-1", "time": "100.0"}
STEP = {"name": "a", "depends": [], "status": "succeeded", "kind": None}
DAG = {"name": "d", "status": "succeeded", "runId": "r", "startedAt": "", "finishedAt": "", "steps": [STEP]}
RUN = {"runId": "r2", "status": "running", "startedAt": "", "step": "a", "stepStartedAt": "", "steps": {"a": "running"}}
POOL = {"name": "lane", "cap": 1, "running": 1, "queued": 0}
BUSY = {**DAG, "active": [RUN], "pool": "lane"}


def adapter(kit: type[_AdapterKit], records: list[dict], **overrides: object) -> _AdapterKit:
    """An adapter of `kit`'s contract producing `records` on the fixture machines, its keys PROJ and its branch examples valid unless overridden."""
    attrs = {
        "keys": PROJ,
        "branches": BRANCHES,
        "machines": MACHINES,
        "teams": TEAMS,
        "produce": lambda self: records,
        **overrides,
    }
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


def test_an_adapter_reporting_active_runs_and_pools_passes_every_check() -> None:
    busy = adapter(RunsAdapterKit, [BUSY], produce_pools=lambda self: [POOL])

    assert [failing(check) for check in every_check(busy)] == [False] * len(every_check(busy))


@pytest.mark.parametrize(
    ("records", "pools", "what"),
    [
        (
            [{**BUSY, "active": [{**RUN, "steps": {"ghost": "running"}}]}],
            [POOL],
            "an active run reporting a ghost step",
        ),
        ([{**BUSY, "active": [{**RUN, "step": "ghost"}]}], [POOL], "an active run currently in a ghost step"),
        ([{**BUSY, "active": [RUN, RUN]}], [POOL], "two active runs of one id"),
        ([{**BUSY, "active": [{**RUN, "status": "succeeded"}]}], [POOL], "an active run that is not in flight"),
        ([BUSY], [], "a DAG naming a pool the adapter does not report"),
        ([BUSY], [POOL, POOL], "a pool reported twice"),
        ([BUSY], [{**POOL, "cap": -1}], "a pool the contract rejects"),
    ],
)
def test_an_adapter_whose_active_runs_or_pools_break_the_contract_fails_a_check(
    records: list[dict], pools: list[dict], what: str
) -> None:
    checks = every_check(adapter(RunsAdapterKit, records, produce_pools=lambda self: pools))

    assert any(failing(check) for check in checks), what


@pytest.mark.parametrize(
    ("kit", "records", "what"),
    [
        (BoardAdapterKit, [], "no records"),
        (BoardAdapterKit, [{**TASK, "title": None}], "a record the contract rejects"),
        (BoardAdapterKit, [{**TASK, "id": "OPS-1"}], "a key outside the declared scheme"),
        (BoardAdapterKit, [{**TASK, "lane": "no_such_lane"}], "a lane the Board machine lacks"),
        (BoardAdapterKit, [{**TASK, "team": "OPS"}], "a team other than the one the adapter declares deriving"),
        (BoardAdapterKit, [{**TASK, "team": ""}], "a task with no team"),
        (BoardAdapterKit, [TASK, {**TASK, "id": "PROJ-2"}], "a task whose team the adapter never declared"),
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


OPEN = {"allowed": True}
OPERATOR_ONLY = {"allowed": True, "writers": ["operator"]}
WRITING_TASK = {**TASK, "moves": {"review": OPEN, "to_do": OPERATOR_ONLY}}


def written(task: str, status: str, actor: str) -> Written:
    return Written(True, "")


def refused(task: str, status: str, actor: str) -> Written:
    return Written(False, "no")


def move_checks(adapter: _AdapterKit) -> list[Callable[[], None]]:
    return [getattr(adapter, name) for name in dir(adapter) if name.startswith("test_") and "move" in name]


def test_a_board_with_a_writer_and_an_operator_only_move_passes_the_move_checks() -> None:
    writing = adapter(BoardAdapterKit, [WRITING_TASK], writer=staticmethod(written))

    assert len(move_checks(writing)) == 2
    assert [failing(check) for check in move_checks(writing)] == [False, False]


@pytest.mark.parametrize(
    ("task", "writer", "what"),
    [
        ({**TASK, "moves": {"review": OPEN}}, written, "no move reserved to the operator"),
        (WRITING_TASK, refused, "a writer that refuses the move it offers"),
    ],
)
def test_a_board_writer_that_breaks_the_move_contract_fails_a_move_check(
    task: dict, writer: Callable, what: str
) -> None:
    checks = move_checks(adapter(BoardAdapterKit, [task], writer=staticmethod(writer)))

    assert any(failing(check) for check in checks), what


def test_a_board_without_a_writer_skips_the_move_checks() -> None:
    assert [failing(check) for check in move_checks(adapter(BoardAdapterKit, [TASK]))] == [False, False]


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
