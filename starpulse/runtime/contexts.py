"""`starpulse worker contexts`: the background contexts as threads of one process over one replica.

Each context (Board, Delivery, Scheduler, Runs, Flow Metrics, Search and the run Adapters) keeps the `start` its own
`starpulse worker <context>` process runs; here each runs on a thread named `ctx-<name>` over one event log, one board
and one read-model fold, where `serve` today supervises a process for each.

A context whose `start` raises is stopped, waits a growing backoff and starts again on its own thread, while every other
context's thread stays. A context that hangs, or whose loop dies after `start` returned, is not restarted. `SIGTERM`
stops every context; `SIGHUP` reloads each one that started.

This module is part of the composition root (`starpulse.runtime`): it imports each bin lazily, as no context imports
`runtime`.
"""

import argparse
import logging
import os
import sys
import threading
import time
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from starpulse.board.model.adapter_types import ADAPTER_CONTEXTS
from starpulse.event_log import child_cpu
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.event_log.wake import StopEvent
from starpulse.runtime.config import Config, rehearsing
from starpulse.runtime.hold import BOOT_ENV, CLAUDE_CODE_FD_ENV, GITHUB_FD_ENV
from starpulse.runtime.readiness import stamp

logger = logging.getLogger(__name__)

#: Starts one context on the stop event it is given and returns its reload.
Starter = Callable[[threading.Event], Callable[[], None]]

#: The first and the longest wait, in seconds, before a context whose start raised starts again; each wait doubles.
BACKOFF_S = (1.0, 30.0)

_JOIN_S = 5.0

#: How long a thread keeps the interpreter before another may take it, in seconds. The default 5 ms made a thread that
#: calls SQLite many times per event (the history recorder) wait that long for each call behind a CPU-bound context:
#: 305 events/s alone fell to 4 with two such threads, and the machine-event copy fell minutes behind.
SWITCH_INTERVAL_S = 0.0005


#: The context that starts first: the others wait for its first start, so a replaced process folds the Board before
#: anything else competes for it (the Board Writer Folds Through a Deploy: a writer down is a page stale).
LEADER = "board"

#: The contexts that always run here, in start order; the run Adapters follow them (`adapter_contexts`).
BACKGROUND_CONTEXTS = (
    "scheduler",
    "runs",
    "flow-metrics",
    "signal-folds",
    "lane-metrics",
    "search",
    "board",
    "sweeper",
)

#: The contexts a rehearsal runs: the rest poll a service, start a session or a run, run a declared command or listen on a port.
REHEARSED_CONTEXTS = ("flow-metrics", "signal-folds", "board")


def contexts_of(config: Config) -> list[str]:
    """The contexts this process runs for `config`: `BACKGROUND_CONTEXTS`, Search only with an `embeddings_url`, then the
    run Adapters its `[[runs]]` instances name, then the receivers its `[claude_code]` and `[github]` tables ask for;
    `REHEARSED_CONTEXTS` alone under a rehearsal."""
    from starpulse.runtime.supervisor import adapter_contexts

    if rehearsing():
        return list(REHEARSED_CONTEXTS)
    kept = [c for c in BACKGROUND_CONTEXTS if c != "search" or config.search.embeddings_url]
    github_events = config.github and config.bridge.enabled and any(p.name == "github" for p in config.producers)
    receivers = [
        name
        for name, table in (
            ("bridge", config.bridge.enabled),
            ("claude-code", config.claude_code),
            ("github", config.github),
            ("github-events", github_events),
        )
        if table
    ]
    return [*kept, *adapter_contexts(config), *receivers]


class _Refusing(argparse.ArgumentParser):
    """The parser `run_adapters` reports a bad runs instance to: it raises where a worker's parser would exit."""

    def exit(self, status: int = 0, message: str | None = None) -> Any:
        raise ValueError((message or "").strip())


class _SharedBoard:
    """The one board and feed of the process: the Board context's when it runs here, otherwise built on first use."""

    def __init__(self, names: Sequence[str], build: Callable[[], tuple[Any, Any]], stop: StopEvent) -> None:
        self._owned = "board" in names
        self._build = build
        self._stop = stop
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._built: tuple[Any, Any] | None = None

    def publish(self, board: Any, feed: Any) -> None:
        self._built = (board, feed)
        self._ready.set()

    def peek(self) -> tuple[Any, Any] | None:
        """The board and feed when the Board context has published them, else None; never waits."""
        return self._built

    def get(self) -> tuple[Any, Any]:
        """The board and feed, waiting for the Board context to publish them; raises when the process stops first."""
        if not self._owned:
            with self._lock:
                if self._built is None:
                    self.publish(*self._build())
        self._stop.listen(self._ready.set)
        try:
            if not self._stop.is_set():  # a stop set before `listen` calls nothing
                self._ready.wait()
        finally:
            self._stop.unlisten(self._ready.set)
        if self._built is None:
            raise RuntimeError("stopped before the board was built")
        return self._built

    def __call__(self, *_args: object, **_kwargs: object) -> tuple[Any, Any]:
        return self.get()


class _SharedStore:
    """The one history store of the process, built by the first context that asks, as `serve` shares its one: a store
    for each context is a database engine, its pool and page caches for each."""

    def __init__(self, build: Callable[..., Any]) -> None:
        self._build = build
        self._lock = threading.Lock()
        self._store: Any = None

    def __call__(self, config: Config, base: Path, machines: Mapping[str, dict]) -> Any:
        with self._lock:
            if self._store is None:
                self._store = self._build(config, base, machines)
            return self._store


class _PullLinks:
    """The task a pull request is linked to: the unarchived task whose references hold its URL."""

    def __init__(self, model: Any) -> None:
        self._model = model

    def task_for(self, repository: str, number: int) -> str | None:
        cited = self._model.citing(f"https://github.com/{repository}/pull/{number}")
        return cited[0] if cited else None


def default_starters(
    config: Config,
    path: Path | None,
    base: Path,
    log: EventLog,
    names: Sequence[str],
    stop: StopEvent,
    go: threading.Event | None = None,
) -> dict[str, Starter]:
    """The starter of each context in `names`, all over `log` and one board; with `go`, the Board writer starts as a standby
    that takes over the writer role when `go` is set. Raises `ValueError` for a name that is no
    context or a `[[runs]]` instance whose adapter the config cannot load."""
    from starpulse.runtime.assembly import (
        assemble,
        board_kinds,
        declared,
        github_kinds,
        own_pull_merged,
        prune_steps,
        worker_board,
    )
    from starpulse.runtime.assembly import history_store as build_history_store
    from starpulse.runtime.config import load
    from starpulse.runtime.read_model_follow import follow

    history_store = _SharedStore(build_history_store)
    shared = _SharedBoard(names, lambda: worker_board(config, base, log, stop), stop)
    adapters: Sequence[Any] = []
    if "runs" in names or "board" in names or any(name in names for name in ADAPTER_CONTEXTS):
        from starpulse.runtime.wiring import run_adapters

        adapters = run_adapters(_Refusing(), config)

    def board(own: threading.Event) -> Callable[[], None]:
        from starpulse.board.bin import board_worker
        from starpulse.event_log.readmodel.snapshot_store import SnapshotStore
        from starpulse.runtime.store_refold import spawn
        from starpulse.runtime.writer_followers import feed_followers
        from starpulse.views.model.encoding import encode_snapshot

        return board_worker.start(
            config, path, base, log, own, load=load, assemble=assemble, history_store=history_store, follow=follow,
            followers=feed_followers(adapters), refold=spawn, ready=shared.publish,
            snapshots=SnapshotStore(log.engine, encode_snapshot), go=go,
        )  # fmt: skip

    def scheduler(own: threading.Event) -> Callable[[], None]:
        from starpulse.runtime.assembly import scheduler_board
        from starpulse.scheduler.bin import scheduler_worker
        from starpulse.bridge.account_room import account_room
        from starpulse.sessions.adapters.outbound.claude_code_notify import end_with
        from starpulse.sessions.adapters.outbound.session_start import starter

        return scheduler_worker.start(
            config, path, base, log, own, load=load,
            worker_board=lambda *_: scheduler_board(config, base, log, own),
            starter=starter, delivered=own_pull_merged, ender=end_with,
            rooms=account_room,
        )  # fmt: skip

    def runs(own: threading.Event) -> Callable[[], None]:
        from starpulse.runs.bin import runs_worker
        from starpulse.runs.model import opt_in

        return runs_worker.start(
            config, path, base, log, own, load=load, adapters=opt_in.followed_by(adapters, None), worker_board=shared,
            history_store=history_store,
        )  # fmt: skip

    def adapter(name: str) -> Starter:
        def start(own: threading.Event) -> Callable[[], None]:
            from starpulse.runs.bin import adapter_worker
            from starpulse.runs.model import opt_in

            return adapter_worker.start(
                config, path, base, log, own, load=load, worker_board=shared,
                adapters=opt_in.followed_by(adapters, name),
            )  # fmt: skip

        return start

    def flow_metrics(own: threading.Event) -> Callable[[], None]:
        from starpulse.flow_metrics.bin import flow_metrics_worker

        # its own cheap `declared`, never `shared`: the recorder needs only the machines, and the shared board waits for the Board context's fold, minutes after a restart
        return flow_metrics_worker.start(
            config, path, base, log, own, load=load, declared=declared, history_store=history_store,
        )  # fmt: skip

    def signal_folds(own: StopEvent) -> Callable[[], None]:
        # the api worker reads the fold rows; counting their cost and summing each task's spend here keeps both off its GIL
        from starpulse.views.adapters.outbound.signal_folds import SignalFolds
        from starpulse.views.adapters.outbound.task_spend import TaskSpend

        _, feed = shared()
        folds = SignalFolds(log, feed.titled)
        threading.Thread(target=folds.follow, args=(own,), name="signal-folds", daemon=True).start()
        threading.Thread(target=TaskSpend(log).follow, args=(own,), name="task-spend", daemon=True).start()
        return lambda: logger.info("signal-folds: the analytics config is read at start; restart to apply a change")

    def lane_metrics(own: threading.Event) -> Callable[[], None]:
        # the api worker serves the text these followers keep in the log, so their catch-up and sweep stay off its GIL
        from starpulse.board.adapters import lane_metrics as followers
        from starpulse.board.adapters.search import SearchIndex

        board, feed = shared()
        search = SearchIndex.open(log.engine, config.search) if config.search.embeddings_url else None
        followers.start(feed, log, own, vectors=search.embed_missing if search is not None else None)
        return lambda: logger.info("lane-metrics: the board config is read at start; restart to apply a change")

    def conformance(own: threading.Event) -> Callable[[], None]:
        # its own worker: a replay of the retained log would crawl on the GIL the contexts share, and the exports stay
        # hidden until the monitor has caught up
        from starpulse.board.adapters import lane_metrics as followers
        from starpulse.event_log.conformance_monitor import BOARD
        from starpulse.flow_metrics.model.liveness import work_machines
        from starpulse.harness_telemetry.model.harness import SESSION_MACHINES

        board, feed = shared()
        followers.monitor(
            feed,
            board,
            log,
            own,
            work_machines(feed.machines, BOARD, feed.roles.working),
            sessions=SESSION_MACHINES,
            types=config.board.get("types", ()),
        )
        return lambda: logger.info("conformance: the board config is read at start; restart to apply a change")

    def sweeper(own: threading.Event) -> Callable[[], None]:
        from starpulse.sweeper.bin import sweeper_worker

        return sweeper_worker.start(
            config,
            path,
            base,
            log,
            own,
            load=load,
            prune=prune_steps(log, config, base),
            contexts=[*board_kinds(shared), *github_kinds(config, log)],
        )

    def bridge(own: threading.Event) -> Callable[[], None]:
        from starpulse.bridge import worker
        from starpulse.event_log.claude_sessions import live_socket, sessions_dir
        from starpulse.machine_engine.model.transitions import lane_id
        from starpulse.pulls.adapters.outbound.pulls import stored_head
        from starpulse.runtime.session_delivery import exit_watcher, forget_ended, route, running
        from starpulse.sessions.adapters.outbound import claude_code_notify as claude
        from starpulse.sessions.adapters.outbound.registry import Registry, directory
        from starpulse.sessions.adapters.outbound.wake_metrics import Wakes
        from starpulse.sessions.identity import same_session

        def lane_of(task: str) -> str | None:
            built = shared.peek()
            if built is None:
                return "unknown"
            row = built[1].task(task, lean=True)
            return lane_id(str(row.get("state") or "")) if row else None

        def closed(task: str) -> bool:
            built = shared.peek()
            return built is not None and (built[1].is_done(task) or built[1].is_archived(task))

        def frozen(task: str) -> bool:
            built = shared.peek()
            row = built[1].task(task, lean=True) if built else None
            return bool(row and row.get("frozen"))

        def held_by(session: str) -> str | None:
            built = shared.peek()
            if built is None:
                return None
            return next(
                (row["id"] for row in built[1].open_tasks() if same_session(row.get("assignee"), session)), None
            )

        notifier = claude.ClaudeCodeNotifier(
            post=claude.post_inbox,
            resume=claude.resume_with(config.bridge.resume),
            alive=live_socket(sessions_dir(os.environ)),
            now=time.monotonic,
            delivered=Wakes(log, lane_of),
        )
        registry = Registry(directory(base, config.bridge.sessions_dir))
        events = None
        if config.producers:
            from starpulse.pulls.adapters.outbound.github import GITHUB_MACHINES
            from starpulse.runs.adapters.inbound.cloudevents import CloudEventsIngest
            from starpulse.runs.adapters.inbound.ingest import tokens as ingest_tokens
            from starpulse.runtime.assembly import declared

            events = CloudEventsIngest(
                {p.name: p for p in config.producers},
                ingest_tokens(config.producers, os.environ),
                log,
                {**declared(config, base)[1], **GITHUB_MACHINES},
            )
        forgotten: set[str] = set()
        return worker.start(
            config.bridge.port,
            config.bridge.board,
            config.bridge.subscriptions,
            log,
            lambda: shared()[1],
            own,
            route(
                registry,
                notifier,
                sessions_dir(os.environ),
                config.bridge.quiet_moves,
                lambda repo, number: stored_head(log.engine, repo, number),
                lane_of,
                lambda: shared()[1].roles.working,
                closed,
                forgotten,
                frozen,
            ),
            forget_ended(registry, live_socket(sessions_dir(os.environ)), sessions_dir(os.environ), forgotten),
            config.bridge.incidents,
            exit_watcher(log, registry, sessions_dir(os.environ), held_by),
            events,
            running(sessions_dir(os.environ)),
        )

    def search(own: threading.Event) -> Callable[[], None]:
        from starpulse.board.bin import search_worker

        return search_worker.start(config, path, base, log, own, load=load)

    def claude_code(own: threading.Event) -> Callable[[], None]:
        from starpulse.harness_telemetry.adapters.inbound import claude_code as receiver

        return receiver.start(config, log, own, receiving)

    # once each: a second socket object on a descriptor would close it when the first is collected
    listening = receiving = None
    if "github" in names or "claude-code" in names:
        from starpulse.runtime.listen import handed_socket

        listening = handed_socket(GITHUB_FD_ENV) if "github" in names else None
        receiving = handed_socket(CLAUDE_CODE_FD_ENV) if "claude-code" in names else None

    def github(own: threading.Event) -> Callable[[], None]:
        from starpulse.event_log.event_log import unpooled_engine
        from starpulse.github.adapters.inbound import listener

        return listener.start(config, own, unpooled_engine(log.engine), listening)

    def github_events(own: threading.Event) -> Callable[[], None]:
        from starpulse.bridge.ingest import Producer
        from starpulse.event_log.readmodel.read_model import ReadModel
        from starpulse.event_log.watch import open_watch
        from starpulse.github.adapters.inbound import consumer
        from starpulse.runs.adapters.inbound.status_resync import Resync

        producer = next((p for p in config.producers if p.name == "github"), None)
        token = os.environ.get(producer.token_env, "") if producer else ""
        if not token:
            raise ValueError("github-events: the producer github holds no token in the environment")
        woodpecker = {
            urllib.parse.urlsplit(run.url or "").path.strip("/"): run.name
            for run in config.runs
            if run.type == "woodpecker"
        }
        return consumer.start(
            config,
            own,
            log.engine,
            Producer(f"nats://127.0.0.1:{config.bridge.port}", config.bridge.board, token),
            _PullLinks(ReadModel(log.engine)),
            open_watch,
            Resync(log, woodpecker),
        )

    known: dict[str, Starter] = {
        "board": board, "scheduler": scheduler, "runs": runs, "flow-metrics": flow_metrics,
        "signal-folds": signal_folds, "lane-metrics": lane_metrics, "conformance": conformance, "search": search, "sweeper": sweeper, "bridge": bridge, "claude-code": claude_code,
        "github": github, "github-events": github_events, **{name: adapter(name) for name in ADAPTER_CONTEXTS},
    }  # fmt: skip
    unknown = [name for name in names if name not in known]
    if unknown:
        raise ValueError(f"no such context: {', '.join(unknown)}")
    return {name: known[name] for name in names}


def _keep(
    name: str,
    starter: Starter,
    stop: StopEvent,
    reloads: dict[str, Callable[[], None]],
    stops: dict[str, threading.Event],
    backoff: tuple[float, float],
    started: Callable[[str], None] | None = None,
    *,
    gate: threading.Event | None = None,
    go: threading.Event | None = None,
    prepared: Callable[[], None] | None = None,
) -> None:
    """Start the context on its own stop event, again after a growing wait each time `starter` raises, then hold the
    thread until the process stops. A failed start's stop event is set, so what it began before raising ends. `started`
    is told the name once `starter` returns; a failure of its own is logged, never a failed start.

    The `LEADER` sets `gate` once its first start attempt has returned or raised; every other context waits for `gate`
    before its first start, so the leader's start is never one of several competing for the process.

    A standby process (`go`) is a replacement preparing beside the process it replaces: the leader's start is its
    prepare, `prepared` is told once it returns, and every other context waits for `go` before its first start. The
    leader's stop event is set by `run_contexts` after every other context ended, so the Board stays the last to go."""
    leads = name == LEADER
    if gate is not None and not leads:
        gate.wait()
    if go is not None and not leads:
        go.wait()
    wait = backoff[0]
    while not stop.is_set():
        own = StopEvent()
        stops[name] = own
        try:
            reloads[name] = starter(own)
        except Exception:
            logger.exception("%s: start failed; starting again in %.1f s", name, wait)
            own.set()
            if gate is not None and leads:
                gate.set()
            # adr-exempt: retry
            if stop.wait(wait):
                return
            wait = min(wait * 2, backoff[1])
            continue
        logger.info("%s: started", name)
        if leads and gate is not None:
            gate.set()
        if leads and prepared:
            prepared()
        if started:
            try:
                started(name)
            except Exception:
                logger.exception("%s: could not record its start", name)
        stop.wait()
        if not leads:
            own.set()
        return


def run_contexts(
    config: Config,
    path: Path | None,
    names: Sequence[str],
    stop: StopEvent,
    *,
    base: Path | None = None,
    starters: Mapping[str, Starter] | None = None,
    hold: Callable[[threading.Event, Callable[[], None]], None] | None = None,
    backoff: tuple[float, float] = BACKOFF_S,
    started: Callable[[str], None] | None = None,
    go: threading.Event | None = None,
    prepared: Callable[[], None] | None = None,
    child: str = "contexts",
) -> None:
    """Run each context of `names` on a `ctx-<name>` thread until `stop` is set, and return once they are told to end.

    `starters` replaces the real starters (tests); `started` is told each context's name as it starts, and without it a
    `serve` boot token (`hold.BOOT_ENV`) makes each start stamp the event log; `hold` is the wait for `SIGTERM` and `SIGHUP` (`runtime.hold`); `child` names this process for the CPU metric. With `go`, the process is a standby replacement: only the
    leader starts until `go` is set, and `prepared` is told when the leader's start returns.
    Raises `ValueError` before any thread starts when a name is no context or a runs adapter cannot load."""
    sys.setswitchinterval(SWITCH_INTERVAL_S)
    base = base or (path.parent if path else Path.cwd())
    if starters is None:
        log = EventLog(database_url(config.database_url, base))
        child_cpu.keep_process(log, child)
        log.keep_wakes(child)
        starters = default_starters(config, path, base, log, names, stop, go)
        boot = os.environ.get(BOOT_ENV)
        if started is None and boot:

            def started(name: str) -> None:
                stamp(log, name, boot)

    if hold is None:
        from starpulse.runtime.hold import hold
    reloads: dict[str, Callable[[], None]] = {}
    stops: dict[str, threading.Event] = {}
    first = threading.Event() if LEADER in names else None  # the Board writer folds before any other context competes
    threads = [
        threading.Thread(
            target=_keep,
            args=(name, starters[name], stop, reloads, stops, backoff, started),
            kwargs={"gate": first, "go": go, "prepared": prepared},
            name=f"ctx-{name}",
            daemon=True,
        )
        for name in names
    ]
    for thread in threads:
        thread.start()
    if prepared and first is None:  # no Board writer to prepare: the process is as ready as it will be
        prepared()

    def reload_all() -> None:
        for name, reload in list(reloads.items()):
            try:
                reload()
            except Exception:
                logger.exception("%s: reload failed", name)

    try:
        hold(stop, reload_all)
    finally:
        stop.set()
        if first is not None:
            first.set()
        if go is not None:
            go.set()  # a context still waiting to start sees the stop
        for name, own in list(stops.items()):
            if name != LEADER:
                own.set()
        for thread in threads:
            if thread.name != f"ctx-{LEADER}":
                thread.join(_JOIN_S)
        if LEADER in stops:  # the Board writer stores that it stopped last, so its stream is stale for the least time
            stops[LEADER].set()
        for thread in threads:
            thread.join(_JOIN_S)
