"""The task key an adapter declares: its pattern, its branch mapping, and the flow view placing by it."""

import json
import re

import jsonschema
import pytest
from pydantic import BaseModel, ValidationError

from starpulse.contracts import adapters as contracts
from starpulse.contracts.adapters import (
    CONTRACTS,
    SCHEMAS,
    ActiveRun,
    BoardTask,
    Dag,
    MachineEvent,
    Pool,
    RecentRun,
    Step,
    TaskKeys,
)
from starpulse.projections.board_feed import BoardFeed
from starpulse.projections.machine_tasks import MachineTasks
from starpulse.tests.machines import MACHINES
from starpulse.tests.unit.test_machine_tasks import _agents, _entry

PROJ = TaskKeys(key=re.compile(r"PROJ-\d+"), branch=re.compile(r"(?:refs/heads/)?feature/(PROJ-\d+)(?:-|$)"))
NUMBERED = TaskKeys(key=re.compile(r"OPS-\d+"), branch=re.compile(r"agent/task-(\d+)(?:-|$)"), key_format="OPS-{}")


def test_a_key_scheme_matches_only_whole_keys_of_its_pattern() -> None:
    assert [PROJ.matches(k) for k in ("PROJ-123", "PROJ-", "xPROJ-123", "PROJ-123x", "OPS-1")] == [
        True,
        False,
        False,
        False,
        False,
    ]


def test_a_branch_maps_to_its_task_key_through_the_scheme_format() -> None:
    assert PROJ.for_branch("feature/PROJ-123-add-thing") == "PROJ-123"
    assert PROJ.for_branch("refs/heads/feature/PROJ-9") == "PROJ-9"
    assert NUMBERED.for_branch("agent/task-45-x") == "OPS-45"
    assert [PROJ.for_branch(ref) for ref in ("main", "feature/other", "", None)] == [None] * 4


def test_the_flow_view_places_a_task_whose_key_the_adapter_declared() -> None:
    feed = BoardFeed(machines=MACHINES)
    tasks = MachineTasks(feed, keys=PROJ)

    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-123", at=100.0))

    assert [(a["id"], a["state"]) for a in _agents(feed, "in-progress")] == [("PROJ-123", "worktree_ready")]


def test_a_task_outside_the_declared_scheme_is_not_placed() -> None:
    feed = BoardFeed(machines=MACHINES)
    tasks = MachineTasks(feed, keys=NUMBERED)

    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-123", at=100.0))

    assert _agents(feed, "in-progress") == []


@pytest.mark.parametrize("model", [BoardTask, MachineEvent, Dag, Step, ActiveRun, RecentRun, Pool])
def test_every_field_of_a_contract_says_what_it_holds(model: type[BaseModel]) -> None:
    assert model.model_fields
    assert [name for name, field in model.model_fields.items() if not field.description] == []


@pytest.mark.parametrize("name", CONTRACTS)
def test_each_contract_has_a_json_schema_and_the_checked_in_copy_is_current(name: str) -> None:
    checked_in = json.loads((contracts.SCHEMA_DIR / f"{name}.schema.json").read_text())

    assert SCHEMAS[name] == CONTRACTS[name].model_json_schema()
    assert checked_in == SCHEMAS[name], "regenerate with `.venv/bin/python -m starpulse.contracts`"


def test_a_machine_event_is_keyed_by_exactly_one_of_task_or_run() -> None:
    fields = {"machine": "in-progress", "event": "WORKTREE_READY", "actor": "agent", "time": "100.5"}

    assert MachineEvent.model_validate({**fields, "task": "PROJ-7"}).time == 100.5
    assert MachineEvent.model_validate({**fields, "run": "r1"}).task is None
    for keyed in ({}, {"task": "PROJ-7", "run": "r1"}):
        with pytest.raises(ValidationError):
            MachineEvent.model_validate({**fields, **keyed})


def test_a_dag_is_read_under_the_names_the_page_draws() -> None:
    dag = Dag.model_validate(
        {
            "name": "d1",
            "status": "running",
            "runId": "r1",
            "startedAt": "2026-10-02T10:00:00Z",
            "finishedAt": "",
            "steps": [{"name": "a", "depends": [], "status": "not_started", "kind": None}],
        }
    )

    assert dag.model_dump(by_alias=True)["runId"] == "r1"
    assert jsonschema.Draft202012Validator(SCHEMAS["runs"]).is_valid(dag.model_dump(by_alias=True, mode="json"))


DAG = {
    "name": "deliver",
    "status": "running",
    "runId": "r2",
    "startedAt": "2026-10-02T10:05:00Z",
    "finishedAt": "",
    "steps": [{"name": "lint", "depends": [], "status": "running", "kind": None}],
}
ACTIVE = {
    "runId": "r2",
    "status": "running",
    "startedAt": "2026-10-02T10:05:00Z",
    "step": "lint",
    "stepStartedAt": "2026-10-02T10:05:01Z",
    "steps": {"lint": "running", "push": "not_started"},
}


def test_a_dag_that_reports_no_active_runs_or_pool_has_none() -> None:
    dag = Dag.model_validate(DAG)

    assert (dag.active, dag.pool) == ((), "")


def test_a_dag_carries_one_record_per_active_run_and_the_pool_it_runs_on() -> None:
    dag = Dag.model_validate(
        {**DAG, "pool": "deliver", "active": [ACTIVE, {**ACTIVE, "runId": "r3", "status": "queued", "step": ""}]}
    )
    dumped = dag.model_dump(by_alias=True, mode="json")

    assert [(a.run_id, a.status, a.step, a.step_started_at) for a in dag.active] == [
        ("r2", "running", "lint", "2026-10-02T10:05:01Z"),
        ("r3", "queued", "", "2026-10-02T10:05:01Z"),
    ]
    assert dag.active[0].steps == {"lint": "running", "push": "not_started"}
    assert dumped["pool"] == "deliver"
    assert jsonschema.Draft202012Validator(SCHEMAS["runs"]).is_valid(dumped)


RECENT = {
    "runId": "r1",
    "status": "failed",
    "startedAt": "2026-10-02T10:00:00Z",
    "finishedAt": "2026-10-02T10:01:00Z",
    "params": {"AFTER": "a" * 40},
    "steps": {"lint": "succeeded", "push": "failed"},
}


def test_a_dag_has_no_recent_runs_unless_its_adapter_reports_them() -> None:
    assert Dag.model_validate(DAG).recent == ()


def test_a_dag_carries_its_recent_runs_with_their_parameters_and_per_step_status() -> None:
    dag = Dag.model_validate({**DAG, "recent": [RECENT]})
    dumped = dag.model_dump(by_alias=True, mode="json")

    assert (dag.recent[0].run_id, dag.recent[0].params, dag.recent[0].steps["push"]) == ("r1", {"AFTER": "a" * 40}, "failed")
    assert jsonschema.Draft202012Validator(SCHEMAS["runs"]).is_valid(dumped)


def test_a_recent_run_outside_the_status_set_is_refused() -> None:
    with pytest.raises(ValidationError):
        RecentRun.model_validate({**RECENT, "steps": {"lint": "paused"}})


def test_an_active_run_outside_the_status_set_is_refused() -> None:
    assert ActiveRun.model_validate(ACTIVE).status == "running"
    with pytest.raises(ValidationError):
        ActiveRun.model_validate({**ACTIVE, "status": "paused"})
    with pytest.raises(ValidationError):
        ActiveRun.model_validate({**ACTIVE, "steps": {"lint": "paused"}})


def test_a_pool_is_a_name_with_its_capacity_and_load() -> None:
    pool = Pool.model_validate({"name": "deliver", "cap": 32, "running": 5, "queued": 1})

    assert (pool.name, pool.cap, pool.running, pool.queued) == ("deliver", 32, 5, 1)
    assert jsonschema.Draft202012Validator(SCHEMAS["pools"]).is_valid(pool.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        Pool.model_validate({"name": "deliver", "cap": 32, "running": -1, "queued": 0})


def test_a_machine_event_an_adapter_wrote_places_its_task_without_a_stream_entry() -> None:
    feed = BoardFeed(machines=MACHINES)
    tasks = MachineTasks(feed, keys=PROJ)

    tasks.put(MachineEvent(machine="in-progress", event="WORKTREE_READY", task="PROJ-5", actor="hook", time=100.0))
    tasks.put(MachineEvent(machine="in-progress", event="WORKTREE_READY", run="r1", time=101.0))
    tasks.put(MachineEvent(machine="in-progress", event="WORKTREE_READY", task="OPS-5", time=102.0))

    assert [(a["id"], a["state"], a["active"]) for a in _agents(feed, "in-progress")] == [
        ("PROJ-5", "worktree_ready", 100.0)
    ]


@pytest.mark.parametrize("team", [None, "", "   "], ids=["absent", "empty", "blank"])
def test_a_board_task_with_no_team_is_refused(team: str | None) -> None:
    fields = {"id": "PROJ-1", "title": "t", "lane": "to_do", **({} if team is None else {"team": team})}

    with pytest.raises(ValidationError):
        BoardTask.model_validate(fields)


def test_a_board_task_carries_the_team_key_its_adapter_derived() -> None:
    task = BoardTask(id="PROJ-1", title="t", lane="to_do", team="PROJ")

    assert task.model_dump(mode="json")["team"] == "PROJ"
    assert "team" in SCHEMAS["board"]["required"]
