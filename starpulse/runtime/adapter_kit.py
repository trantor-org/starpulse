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
"""

import json
import time
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from http.client import HTTPResponse
from pathlib import Path
from typing import Any, ClassVar

import jsonschema
from pydantic import BaseModel

from starpulse.board.adapters.display_settings import DisplaySettings
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.seam import Board, Written
from starpulse.contracts.adapters import (
    SCHEMAS,
    BoardTask,
    Dag,
    MachineEvent,
    Pool,
    TaskKeys,
)
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.machine_fold import Placer
from starpulse.event_log.wake import StopEvent
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.machine_engine.model.state_roles import StateRoles
from starpulse.machine_engine.model.transitions import DEFAULT_STATUSES
from starpulse.runtime.config import Config
from starpulse.runtime.placed import Placed
from starpulse.runtime.placed import assembled as placed_assembled
from starpulse.runtime.store_migrate import maintain
from starpulse.runtime.stored_snapshot import stored_snapshots
from starpulse.views.adapters.inbound.asgi_app import page_app
from starpulse.views.adapters.inbound.page_server import PageServer
from starpulse.views.ports.services import Services

#: How long a settle or a served page waits for the Board writer to fold what was published.
FOLDED_WITHIN_S = 30.0

__all__ = [
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


# The helpers below drive an adapter through StarPulse's own server and feed.


def _nothing(*_: Any) -> None:
    pass


def _refused(*_: Any, **__: Any) -> Written:
    return Written(False, "this board holds no tasks", unavailable=True)


def _absent(*_: Any) -> None:
    return None


def refusing(**fields: Any) -> Board:
    """A Board that holds no tasks: every write refuses and every read finds nothing; `fields` replace its parts."""
    return Board(
        **{
            "machines": lambda qualify, workflows: {},
            "start": _nothing,
            "keys": None,
            "cues": lambda _qualify: (),
            "waits": {},
            "roles": StateRoles.of_statuses(DEFAULT_STATUSES),
            "writer": _refused,
            "assign": _refused,
            "source": "the events instances forward",
            "read": _absent,
            "read_archived": _absent,
            "edit": _refused,
            "judge": _refused,
            "archive": _refused,
            "restore": _refused,
            "standing": _absent,
            "readable": lambda *_: "",
            "complete": _refused,
            "reopen": _refused,
            "retire": _refused,
            "retired": lambda *_: (),
            "retired_projected": lambda *_: [],
            "retired_page": lambda *_: ([], None),
            "create": _refused,
            "milestones": lambda: [],
            "read_milestone": _absent,
            "create_milestone": _refused,
            "edit_milestone": _refused,
            "archive_milestone": _refused,
            "read_doc": _absent,
            "create_doc": _refused,
            "edit_doc": _refused,
            "archive_doc": _refused,
            "restore_doc": _refused,
            "move_doc": _refused,
            "holds": lambda *_: (),
            "unfinished": lambda *_: (),
            "unpublished": lambda *_: None,
            "parked": _nothing,
            "released": _nothing,
            "idle": None,
            "returned": _nothing,
            "alive": lambda *_: False,
            "enqueued": _nothing,
            "closed": _nothing,
            "archived": _nothing,
            "frozen": _nothing,
            "halted": _nothing,
            "faulted": None,
            "entered": _nothing,
            "attach": _nothing,
            **fields,
        }
    )


@contextmanager
def serve(
    tmp_path: Path,
    feed: BoardFeed | None = None,
    board: Board | None = None,
    *,
    history: HistoryStore | None = None,
    window: HistoryWindow | None = None,
    clock: Callable[[], float] = time.time,
    port: int = 0,
    tls: tuple[Path, Path] | None = None,
    migrated: bool = False,
    **services: Any,
) -> Iterator[PageServer]:
    """Serve a stub build in `tmp_path` until the `with` block ends. `board` is the Board the routes write through (a
    refusing one when None); `services` are the `Services` fields.
    `migrated` says the stores in `tmp_path` are already migrated, so the serve skips the pass that migrates them."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True, exist_ok=True)
    (static / "index.html").write_text("<!doctype html>")
    (static / "assets" / "index-abc123.js").write_text("")
    (tmp_path / "secret.txt").write_text("")
    drawn = None if feed else Placed()
    served = feed or drawn.draw()
    machines = feed.machines if feed else {}
    settings, kept = f"sqlite:///{tmp_path / 'settings.sqlite'}", f"sqlite:///{tmp_path / 'history.sqlite'}"
    for store in () if migrated else (settings, kept):
        maintain(store, machines)
    log = EventLog(settings)
    board = board or refusing()
    stop = StopEvent()
    snapshots = server = None
    try:
        window = window or HistoryWindow(served, 6, log)  # it publishes a snapshot change: before the writer starts, it builds with it
        snapshots = stored_snapshots(served, log, stop)
        app = page_app(
            served,
            snapshots,
            static,
            history or HistoryStore(kept, machines),
            window,
            board,
            Services(display=DisplaySettings(log), **services),
            clock,
        )
        server = PageServer(
            app, ("127.0.0.1", port), tls=tls, stopping=lambda: snapshots.announce("restarting", {"at": time.time()})
        )
        server.caught_up = snapshots.caught_up
        if not snapshots.caught_up(FOLDED_WITHIN_S):  # the window `page_app` drew is folded, or a stream sends it late
            raise TimeoutError(f"the Board writer folded no change in {FOLDED_WITHIN_S} s")
        server.start()
        yield server
    finally:
        if server is not None:
            server.close()
        stop.set()
        # a reader of the log still mid-step reopens it after the close, and a thread starved under load has not begun
        readers = snapshots.readers if snapshots is not None else []
        for reader in readers:
            reader.join(30)
        if running := [reader.name for reader in readers if reader.is_alive()]:
            raise RuntimeError(f"a reader still runs 30 s after the stop, so the log stays open: {running}")
        log.close()
        if drawn:
            drawn.close()


def url(server: PageServer, path: str) -> str:
    return f"http://127.0.0.1:{server.server_port}{path}"


def subscribe(server: PageServer, query: str, variables: dict[str, Any] | None = None) -> HTTPResponse:
    """The open `/graphql` stream of the subscription `query`, whose first `next` event `next_event` reads."""
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    request = urllib.request.Request(url(server, "/graphql"), data=body, headers={"content-type": "application/json"})
    return urllib.request.urlopen(request, timeout=5)


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
    board, feed, _ = placed_assembled(config, base)
    return board, feed
