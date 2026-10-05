"""The test kit an adapter author runs against their adapter.

Subclass the kit for the contract the adapter writes, declare the adapter's task keys and branch
examples, and say how to produce its records; pytest collects the checks on the subclass:

    class TestMyBoard(BoardAdapterKit):
        keys = TaskKeys(key=re.compile(r"PROJ-\\d+"), branch=re.compile(r"feature/(PROJ-\\d+)"))
        branches = {"feature/PROJ-1-add-x": "PROJ-1", "main": None}

        def produce(self) -> list[dict]:
            return [{"id": "PROJ-1", "title": "Add x", "lane": "in_progress"}]

`produce` returns the records the adapter writes for StarPulse, as plain dicts shaped as the
contract's JSON Schema (`starpulse.contracts.SCHEMAS`). A machine event may carry its `time` as text,
as a stream does. The kit checks each record against the contract and its schema, checks task keys
and branch examples against the adapter's `TaskKeys`, and hands the records to StarPulse's own
feeds to see that each is placed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import ClassVar

import jsonschema
from pydantic import BaseModel

from starpulse.board import MoveWriter, Written
from starpulse.board_feed import BoardFeed
from starpulse.contracts import SCHEMAS, BoardTask, Dag, MachineEvent, TaskKeys
from starpulse.machine_tasks import MachineTasks
from starpulse.server import move_task

__all__ = ["BoardAdapterKit", "MachineEventsAdapterKit", "RunsAdapterKit"]


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


class BoardAdapterKit(_AdapterKit):
    """For an adapter writing `BoardTask` records."""

    _name = "board"
    _model = BoardTask
    #: The machines the page draws, the Board's as `board`, as the adapter's `starpulse.board.Board` draws them.
    machines: ClassVar[Mapping[str, dict]]
    #: The adapter's board writer over the project `produce` reads, when it has one; with a writer, `produce` offers
    #: a move any actor may make and one the machine leaves to the operator.
    writer: MoveWriter | None = None

    def test_every_task_key_is_in_the_declared_scheme(self) -> None:
        assert [t.id for t in self.records() if not self.keys.matches(t.id)] == []

    def _move(self, actor: str, permitted: bool) -> tuple[tuple[int, dict], list[str]]:
        """Ask the server to make the first offered move `actor` is (`permitted`) or is not allowed; the writer's calls."""
        assert self.writer is not None
        calls: list[str] = []

        def write(task: str, status: str, by: str) -> Written:
            calls.append(task)
            assert self.writer is not None
            return self.writer(task, status, by)

        feed = BoardFeed(keys=self.keys, machines=self.machines)
        records = self.records()
        for task in records:
            feed.put(task)
        offered = [
            (task.id, column)
            for task in records
            for column, move in task.moves.items()
            if move.allowed and move.permits(actor) == permitted
        ]
        assert offered, f"produce() offers no move that {actor} {'may' if permitted else 'may not'} make"
        task, column = offered[0]
        raw = json.dumps({"task": task, "to": column, "actor": actor}).encode()
        return move_task("127.0.0.1", raw, feed, write), calls

    def test_a_move_the_actor_may_make_is_written_by_the_board_writer(self) -> None:
        if self.writer is None:
            return
        (status, reply), calls = self._move("operator", permitted=True)
        assert (status, calls != []) == (200, True), reply

    def test_a_move_the_machine_leaves_to_others_is_refused_to_an_agent_before_the_writer(self) -> None:
        if self.writer is None:
            return
        (status, reply), calls = self._move("agent", permitted=False)
        assert (status, calls) == (409, []), reply

    def test_the_flow_view_places_every_task_in_its_lane_or_as_settled(self) -> None:
        feed = BoardFeed(keys=self.keys, machines=self.machines)
        for task in self.records():
            feed.put(task)
        lanes = {state["id"] for state in self.machines["board"]["states"]}
        latest = {task.id: task for task in self.records()}
        snapshot = feed.snapshot()
        assert snapshot["flows"][0]["machine"] == self.machines["board"]
        placed = {a["id"]: a["state"] for a in snapshot["flows"][0]["agents"]}
        assert {t.id: t.lane for t in latest.values() if not t.settled} == placed
        assert {t.id: t.settled for t in latest.values() if t.settled} == snapshot["settled"]
        assert set(placed.values()) - lanes == set()


class MachineEventsAdapterKit(_AdapterKit):
    """For an adapter writing `MachineEvent` records."""

    _name = "machine-events"
    _model = MachineEvent
    #: The machines the adapter's events move, as the page draws them.
    machines: ClassVar[Mapping[str, dict]]

    def test_every_task_key_is_in_the_declared_scheme(self) -> None:
        assert [e.task for e in self.records() if e.task and not self.keys.matches(e.task)] == []

    def test_every_event_names_a_machine_and_event_the_flow_view_draws(self) -> None:
        drawn = {name: {t["event"] for t in machine["transitions"]} for name, machine in self.machines.items()}
        assert [(e.machine, e.event) for e in self.records() if e.event not in drawn.get(e.machine, ())] == []

    def test_the_flow_view_places_every_task_an_event_moved(self) -> None:
        feed = BoardFeed(machines=self.machines)
        tasks = MachineTasks(feed, keys=self.keys, machines=self.machines)
        events = [e for e in self.records() if e.task]
        for event in events:
            tasks.put(event)
        placed = {(f["name"], a["id"]) for f in feed.snapshot()["flows"] for a in f["agents"]}
        assert {(e.machine, e.task) for e in events} == placed


class RunsAdapterKit(_AdapterKit):
    """For an adapter writing `Dag` records."""

    _name = "runs"
    _model = Dag

    def test_every_step_waits_only_on_steps_of_its_own_dag(self) -> None:
        for dag in self.records():
            names = [step.name for step in dag.steps]
            assert len(names) == len(set(names)), f"{dag.name} repeats a step name"
            assert [d for step in dag.steps for d in step.depends if d not in names] == []

    def test_the_flow_view_draws_every_dag(self) -> None:
        feed = BoardFeed()
        dags = self.produce()
        feed.runs("kit").set_dags(dags, None)
        assert feed.snapshot()["dags"] == [{**dag, "name": f"kit/{dag['name']}"} for dag in dags]
