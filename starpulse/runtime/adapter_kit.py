"""The test kit an adapter author runs against their adapter.

Subclass the kit for the contract the adapter writes, declare the adapter's task keys and branch
examples, and say how to produce its records; pytest collects the checks on the subclass:

    class TestMyEvents(MachineEventsAdapterKit):
        keys = TaskKeys(key=re.compile(r"PROJ-\\d+"), branch=re.compile(r"feature/(PROJ-\\d+)"))
        branches = {"feature/PROJ-1-add-x": "PROJ-1", "main": None}
        machines = {"in-progress": {...}}

        def produce(self) -> list[dict]:
            return [{"task": "PROJ-1", "machine": "in-progress", "event": "WORKTREE_READY", "time": 1.7e9}]

`produce` returns the records the adapter writes for StarPulse, as plain dicts shaped as the
contract's JSON Schema (`starpulse.contracts.SCHEMAS`). A machine event may carry its `time` as text,
as a stream does. The kit checks each record against the contract and its schema, checks task keys
and branch examples against the adapter's `TaskKeys`, and hands the records to StarPulse's own
feeds to see that each is placed.

The helpers that serve a build for the kit's tests live in `serve_kit` and `task_kit`, and are exported here.
"""

from collections.abc import Mapping
from typing import ClassVar

import jsonschema
from pydantic import BaseModel

from starpulse.contracts.adapters import SCHEMAS, Dag, MachineEvent, Pool, TaskKeys
from starpulse.event_log.readmodel.machine_fold import Placer
from starpulse.runtime.placed import Placed
from starpulse.runtime.serve_kit import assembled, next_event, serve, subscribe, url
from starpulse.runtime.task_kit import task

__all__ = [
    "MachineEventsAdapterKit",
    "RunsAdapterKit",
    "assembled",
    "next_event",
    "serve",
    "subscribe",
    "task",
    "url",
]


class _AdapterKit:
    """The checks every contract shares; a subclass names the contract and what a record's task key is."""

    #: The adapter's task key pattern and branch mapping.
    keys: ClassVar[TaskKeys]
    #: Branch names the adapter maps to a task key (or None for a branch that names no task); at least one of each.
    branches: ClassVar[Mapping[str, str | None]]
    _name: ClassVar[str]
    _model: ClassVar[type[BaseModel]]

    def produce(self) -> list[dict]:
        """The records the adapter writes; the adapter's test overrides this."""
        raise NotImplementedError("override produce() to return the adapter's records")

    def records(self) -> list:
        """What `produce` returned, parsed as the contract."""
        return [self._model.model_validate(record) for record in self.produce()]

    def test_the_adapter_produces_records(self) -> None:
        assert self.produce(), "the adapter produced no records, so nothing is checked"

    def test_every_record_follows_its_contract_and_json_schema(self) -> None:
        for record in self.records():
            jsonschema.validate(record.model_dump(mode="json", by_alias=True), SCHEMAS[self._name])

    def test_the_branch_examples_map_to_the_task_keys_they_declare(self) -> None:
        assert any(key for key in self.branches.values()) and None in self.branches.values(), (
            "declare a branch that names a task and one that names none"
        )
        mapped = {ref: self.keys.for_branch(ref) for ref in self.branches}
        assert mapped == dict(self.branches)
        assert all(self.keys.matches(key) for key in mapped.values() if key)


class MachineEventsAdapterKit(_AdapterKit):
    """For an adapter writing `MachineEvent` records."""

    _name = "machine-events"
    _model = MachineEvent
    #: The machines the adapter's events move, as the page draws them.
    machines: ClassVar[Mapping[str, dict]]

    def test_every_task_key_is_in_the_declared_scheme(self) -> None:
        assert [e.task for e in self.records() if e.task and not self.keys.matches(e.task)] == []

    def test_every_event_names_a_machine_and_event_starpulse_draws(self) -> None:
        drawn = {name: {t["event"] for t in machine["transitions"]} for name, machine in self.machines.items()}
        assert [(e.machine, e.event) for e in self.records() if e.event not in drawn.get(e.machine, ())] == []

    def test_starpulse_places_every_task_an_event_moved(self) -> None:
        placer = Placer(self.machines, self.keys)
        events = [e for e in self.records() if e.task]
        agents: dict[tuple[str, str], dict] = {}
        for event in events:
            placed = placer.place(agents.get((event.machine, event.task)), event)
            if placed is not None:
                flow, task, agent = placed
                agents[flow, task] = agent
        assert {(e.machine, e.task) for e in events} == set(agents)


class RunsAdapterKit(_AdapterKit):
    """For an adapter writing `Dag` records."""

    _name = "runs"
    _model = Dag

    def produce_pools(self) -> list[dict]:
        """The concurrency pools the adapter reports, as plain dicts shaped as the `pools` schema; an adapter with none leaves this empty."""
        return []

    def test_every_step_waits_only_on_steps_of_its_own_dag(self) -> None:
        for dag in self.records():
            names = [step.name for step in dag.steps]
            assert len(names) == len(set(names)), f"{dag.name} repeats a step name"
            assert [d for step in dag.steps for d in step.depends if d not in names] == []

    def test_every_dag_carries_its_schedule_statistics_and_every_step_its_precondition_lock_and_history(self) -> None:
        for dag in self.produce():
            assert {"schedule", "stats", "rerun"} <= dag.keys(), f"{dag['name']} leaves out a schedule, stats or rerun"
            for step in dag["steps"]:
                missing = {"precondition", "lock", "last"} - step.keys()
                assert not missing, f"{dag['name']} step {step['name']} leaves out {sorted(missing)}"

    def test_a_dag_never_run_has_no_statistics_and_the_statistics_of_one_run_add_up(self) -> None:
        for dag in self.records():
            if not dag.run_id:
                assert dag.stats is None, f"{dag.name} never ran, so it has no statistics to report as zeros"
            elif dag.stats is not None:
                stats = dag.stats
                assert (stats.median_seconds is None) == (stats.p95_seconds is None), f"{dag.name} has one duration"
                if stats.median_seconds is not None and stats.p95_seconds is not None:
                    assert stats.median_seconds <= stats.p95_seconds, f"{dag.name} has a median above its p95"
                assert stats.runs > 0 or stats.hours == 0, f"{dag.name} has run-hours but no runs"

    def test_every_active_run_is_in_flight_and_stays_within_its_own_dag(self) -> None:
        for dag in self.records():
            names = {step.name for step in dag.steps}
            ids = [run.run_id for run in dag.active]
            assert len(ids) == len(set(ids)), f"{dag.name} repeats an active run id"
            for run in dag.active:
                assert run.status in ("queued", "running"), f"{dag.name} run {run.run_id} is not queued or running"
                if names:
                    assert set(run.steps) <= names, f"{dag.name} run {run.run_id} reports a step the DAG lacks"
                    assert run.step in names | {""}, f"{dag.name} run {run.run_id} is in a step the DAG lacks"

    def test_every_pool_follows_its_contract_and_every_pool_a_dag_names_is_reported(self) -> None:
        pools = [Pool.model_validate(pool) for pool in self.produce_pools()]
        for pool in pools:
            jsonschema.validate(pool.model_dump(mode="json", by_alias=True), SCHEMAS["pools"])
        names = [pool.name for pool in pools]
        assert len(names) == len(set(names)), "a pool is reported twice"
        assert [dag.name for dag in self.records() if dag.pool and dag.pool not in names] == []

    def test_starpulse_draws_every_dag_and_pool(self) -> None:
        feed = Placed().draw()
        dags, pools = self.produce(), self.produce_pools()
        feed.runs("kit").set_dags(dags, None, pools)
        snapshot = feed.snapshot()
        assert snapshot["dags"] == [
            {**dag, "name": f"kit/{dag['name']}", "startUrl": ""}
            | ({"pool": f"kit/{dag['pool']}"} if dag.get("pool") else {})
            for dag in dags
        ]
        assert snapshot["pools"] == [{**pool, "name": f"kit/{pool['name']}"} for pool in pools]
