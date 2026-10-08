"""The test kit an adapter author runs against their adapter.

Subclass the kit for the contract the adapter writes, declare the adapter's task keys and branch
examples (and, for a board, the team it derives for each task), and say how to produce its records;
pytest collects the checks on the subclass:

    class TestMyBoard(BoardAdapterKit):
        keys = TaskKeys(key=re.compile(r"PROJ-\\d+"), branch=re.compile(r"feature/(PROJ-\\d+)"))
        branches = {"feature/PROJ-1-add-x": "PROJ-1", "main": None}
        teams = {"PROJ-1": "PROJ"}

        def produce(self) -> list[dict]:
            return [{"id": "PROJ-1", "title": "Add x", "team": "PROJ", "lane": "in_progress"}]

`produce` returns the records the adapter writes for StarPulse, as plain dicts shaped as the
contract's JSON Schema (`starpulse.contracts.SCHEMAS`). A machine event may carry its `time` as text,
as a stream does. The kit checks each record against the contract and its schema, checks task keys
and branch examples against the adapter's `TaskKeys`, and hands the records to StarPulse's own
feeds to see that each is placed.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from http.client import HTTPResponse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import jsonschema
from pydantic import BaseModel

from starpulse.adapters.boards.seam import (
    AssigneeWriter,
    Board,
    MoveWriter,
    TaskArchiver,
    TaskCreator,
    TaskEditor,
    TaskReader,
    Written,
)
from starpulse.adapters.runs.ingest import ForwardIngest, Ingest
from starpulse.api.forward import Forwarder
from starpulse.api.server import assemble as _assemble
from starpulse.api.server import move_task, request_handler
from starpulse.contracts.adapters import (
    FINDING_TEXT_MAX,
    SCHEMAS,
    BoardTask,
    Dag,
    Finding,
    MachineEvent,
    Pool,
    TaskKeys,
)
from starpulse.domain.level import Level
from starpulse.projections.board_feed import BoardFeed
from starpulse.projections.insights import Insights, InsightStore
from starpulse.projections.machine_tasks import MachineTasks
from starpulse.settings.config import Config
from starpulse.settings.harnesses import Harnesses
from starpulse.settings.history_window import HistoryWindow
from starpulse.store.history import History, HistoryStore
from starpulse.store.pulls import PullStore

__all__ = [
    "BoardAdapterKit",
    "InsightsEngineKit",
    "MachineEventsAdapterKit",
    "RunsAdapterKit",
    "assembled",
    "next_event",
    "serve",
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


class BoardAdapterKit(_AdapterKit):
    """For an adapter writing `BoardTask` records."""

    _name = "board"
    _model = BoardTask
    #: The machines the page draws, the Board's as `board`, as the adapter's `starpulse.adapters.boards.seam.Board` draws them.
    machines: ClassVar[Mapping[str, dict]]
    #: The team key the adapter derives for each task `produce` returns, by task key: the Backlog.md project, Jira
    #: project or board, or GitHub repository its tracker places the task in. The kit holds each record to it.
    teams: ClassVar[Mapping[str, str]]
    #: The adapter's board writer over the project `produce` reads, when it has one; with a writer, `produce` offers
    #: a move any actor may make and one the machine leaves to the operator.
    writer: MoveWriter | None = None

    def test_every_task_key_is_in_the_declared_scheme(self) -> None:
        assert [t.id for t in self.records() if not self.keys.matches(t.id)] == []

    def test_every_task_is_in_the_team_the_adapter_derives_from_its_tracker(self) -> None:
        assert {t.id: t.team for t in self.records()} == dict(self.teams)

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
        assert {t.id: t.settled for t in latest.values() if t.settled} == {
            id: entry["state"] for id, entry in snapshot["settled"].items()
        }
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

    def produce_pools(self) -> list[dict]:
        """The concurrency pools the adapter reports, as plain dicts shaped as the `pools` schema; an adapter with none leaves this empty."""
        return []

    def test_every_step_waits_only_on_steps_of_its_own_dag(self) -> None:
        for dag in self.records():
            names = [step.name for step in dag.steps]
            assert len(names) == len(set(names)), f"{dag.name} repeats a step name"
            assert [d for step in dag.steps for d in step.depends if d not in names] == []

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

    def test_the_flow_view_draws_every_dag_and_pool(self) -> None:
        feed = BoardFeed()
        dags, pools = self.produce(), self.produce_pools()
        feed.runs("kit").set_dags(dags, None, pools)
        snapshot = feed.snapshot()
        assert snapshot["dags"] == [
            {**dag, "name": f"kit/{dag['name']}"} | ({"pool": f"kit/{dag['pool']}"} if dag.get("pool") else {})
            for dag in dags
        ]
        assert snapshot["pools"] == [{**pool, "name": f"kit/{pool['name']}"} for pool in pools]


class InsightsEngineKit:
    """For an engine posting `Finding` records through the insights API."""

    def produce(self) -> list[dict]:
        """The findings the engine posts; the engine's test overrides this."""
        raise NotImplementedError("override produce() to return the engine's findings")

    def records(self) -> list[Finding]:
        """What `produce` returned, parsed as the contract."""
        return [Finding.model_validate(finding) for finding in self.produce()]

    def test_the_engine_produces_findings(self) -> None:
        assert self.produce(), "the engine produced no findings, so nothing is checked"

    def test_every_finding_follows_its_contract_and_json_schema(self) -> None:
        ids = [finding.id for finding in self.records()]
        assert len(ids) == len(set(ids)), "two findings share an id, so the second replaces the first"
        for finding in self.records():
            jsonschema.validate(finding.model_dump(mode="json"), SCHEMAS["insights"])

    def test_the_hub_stores_replaces_and_retracts_each_finding_and_the_stream_sends_each_state(self) -> None:
        findings = self.records()
        with _insights_stack(min(f.created_at for f in findings)) as (server, feed, store):
            with urllib.request.urlopen(url(server, "/api/events"), timeout=5) as stream:
                assert next_event(stream)[0] == "snapshot"
                for finding in findings:
                    raw = finding.model_dump(mode="json")
                    revised = {**raw, "text": f"Revised: {finding.text}"[:FINDING_TEXT_MAX]}
                    assert _insight(server, "POST", _INSIGHTS, raw) == (201, {"id": finding.id, "replaced": False})
                    assert next_event(stream) == ("insight", {"id": finding.id, "finding": raw})
                    assert _insight(server, "POST", _INSIGHTS, revised) == (200, {"id": finding.id, "replaced": True})
                    assert next_event(stream) == ("insight", {"id": finding.id, "finding": revised})
                    assert [f["text"] for f in feed.snapshot()["insights"] if f["id"] == finding.id] == [
                        revised["text"]
                    ]
                    retraction = _insight(server, "DELETE", f"{_INSIGHTS}/{finding.id}")
                    assert retraction == (200, {"id": finding.id, "retracted": True})
                    assert next_event(stream) == ("insight", {"id": finding.id, "finding": None})
            assert feed.snapshot()["insights"] == [] and store.live(float("inf")) == []

    def test_a_finding_scoped_to_a_person_is_refused_and_leaves_nothing_behind(self) -> None:
        raw = self.records()[0].model_dump(mode="json")
        with _insights_stack(raw["created_at"]) as (server, feed, store):
            for person in ("person", "user", "assignee"):
                status, answer = _insight(
                    server, "POST", _INSIGHTS, {**raw, "scope": {**raw["scope"], person: "alice"}}
                )
                assert status == 400 and person in answer["error"], answer
            assert feed.snapshot()["insights"] == [] and store.live(float("inf")) == []


# The helpers below drive an adapter through the flow view's own server and feed.

_INSIGHTS = "/api/insights"


@contextmanager
def _insights_stack(now: float) -> Iterator[tuple[ThreadingHTTPServer, BoardFeed, InsightStore]]:
    """A server with the insights API over a history store in a temporary SQLite file, its clock at `now`."""
    feed = BoardFeed(clock=lambda: now)
    with tempfile.TemporaryDirectory() as tmp:
        store = InsightStore(f"sqlite:///{tmp}/history.sqlite")
        with serve(Path(tmp), feed, insights=Insights(store, feed, lambda: now)) as server:
            yield server, feed, store


def _insight(server: ThreadingHTTPServer, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        url(server, path), data=None if body is None else json.dumps(body).encode(), method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def _no_writer(task: str, status: str, actor: str = "") -> Written:
    raise AssertionError(f"the test reached the board writer: {task} {status}")


@contextmanager
def serve(
    tmp_path: Path,
    feed: BoardFeed | None = None,
    starts: Mapping[str, Callable[[str], str]] | None = None,
    history: History | None = None,
    run_safe: frozenset[str] = frozenset(),
    writer: MoveWriter | None = None,
    harnesses: Harnesses | None = None,
    assign: AssigneeWriter | None = None,
    start_session: Callable[[str], str] | None = None,
    window: HistoryWindow | None = None,
    read: TaskReader | None = None,
    edit: TaskEditor | None = None,
    archive: TaskArchiver | None = None,
    create: TaskCreator | None = None,
    clock: Callable[[], float] = time.time,
    ingest: Ingest | None = None,
    gate: Callable[[BaseHTTPRequestHandler], bool] | None = None,
    insights: Insights | None = None,
    port: int = 0,
    forward: ForwardIngest | None = None,
    level: Level | None = None,
    forwarding: Forwarder | None = None,
    reruns: Mapping[str, Callable[[str, Mapping[str, str]], str]] | None = None,
    contract: Callable[[], dict[str, Any]] | None = None,
    milestones: Board | None = None,
    pulls: PullStore | None = None,
) -> Iterator[ThreadingHTTPServer]:
    """Serve a stub build in `tmp_path` until the `with` block ends."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True, exist_ok=True)
    (static / "index.html").write_text("<!doctype html>")
    (static / "assets" / "index-abc123.js").write_text("")
    (tmp_path / "secret.txt").write_text("")
    served = feed or BoardFeed()
    handler = request_handler(
        served,
        static,
        starts or {},
        run_safe,
        history or HistoryStore("sqlite://", feed.machines if feed else {}),
        window or HistoryWindow(served, 6, tmp_path / "starpulse-settings.json"),
        writer or _no_writer,
        harnesses,
        assign or _no_writer,
        start_session,
        read,
        edit,
        archive,
        create,
        clock,
        ingest,
        gate,
        forward,
        level,
        insights=insights,
        forwarding=forwarding,
        reruns=reruns,
        contract=contract,
        milestones=milestones,
        pulls=pulls,
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        server.shutdown()


def url(server: ThreadingHTTPServer, path: str) -> str:
    return f"http://127.0.0.1:{server.server_port}{path}"


def next_event(resp: HTTPResponse) -> tuple[str, dict]:
    """The next named event on the stream, skipping its keep-alive comments."""
    name = ""
    while line := resp.readline().decode():
        if line.startswith("event: "):
            name = line.removeprefix("event: ").strip()
        elif line.startswith("data: "):
            return name, json.loads(line.removeprefix("data: "))
    raise AssertionError("the stream ended")


def task(task_id: str, status: str = "To Do", **fields) -> BoardTask:
    """A task in the lane `status` names, its title derived from its key and its team `demo` unless given."""
    return BoardTask(
        id=task_id,
        title=fields.pop("title", f"Title of {task_id}"),
        team=fields.pop("team", "demo"),
        lane=status.lower().replace(" ", "_"),
        **fields,
    )


def assembled(config: Config, base: Path) -> tuple[Board, BoardFeed]:
    """The board the config's `[board]` adapter builds and the feed that draws it, as `starpulse serve` assembles them.

    `base` is the directory the config's relative paths are read from.
    """
    return _assemble(config, base, None, config.qualified_run_safe())
