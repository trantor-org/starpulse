"""`starpulse worker api`: the Page API as its own process, a child `serve` supervises.

`serve` binds the listening socket and hands it to this child on the descriptor `STARPULSE_LISTEN_FD` names
(`Host.listen_fd_env`), so a connection made while the child is being replaced waits in the
socket's backlog for the next one rather than being refused. The child builds the page as `serve` once did: it reads the
Board from the read model the Board child folds and starts no adapter watcher. Started by hand, without a handed
socket, it binds `--host` and `--port` itself.

`SIGTERM` finishes the requests it took (`PageServer.run`); a config change replaces
the process, as the page is built from the whole config once.
"""

import argparse
import dataclasses
import gc
import os
import socket
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

lazy from sqlalchemy.engine import make_url

from starpulse.board.adapters.display_settings import DisplaySettings
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.adapters.holder_idle import dispatcher
from starpulse.board.adapters.lane_metrics import metrics_of as lane_metrics_of
from starpulse.board.adapters.lane_policy import lane_surfaces
from starpulse.board.adapters.native import DEFAULT_PATH
from starpulse.bridge.metrics import metrics_of as bridge_metrics_of
from starpulse.bridge.subjects import CHECKPOINT, STREAMS
from starpulse.event_log.caught_up import CaughtUp
from starpulse.event_log.child_cpu import STATES as CHILDREN
from starpulse.event_log.child_cpu import metrics_of as child_cpu_metrics_of
from starpulse.event_log.follower_wakes import metrics_of as follower_wake_metrics_of
from starpulse.event_log.follower_lag import metrics_of as follower_lag_metrics_of
from starpulse.event_log.recorder_lag import metrics_of as history_lag_metrics_of
from starpulse.event_log.wake import StopEvent
from starpulse.pulls.adapters.inbound.delivery import (
    PROJECTION as PULLS_PROJECTION,
)
from starpulse.pulls.adapters.inbound.delivery import (
    SAVED_STREAM,
    Projected,
    metrics_of,
    refresh_on_save,
)
from starpulse.runs.adapters.inbound.cloudevents import CloudEventsIngest
from starpulse.runs.adapters.inbound.grafana_notice import notice_webhook
from starpulse.runs.application.queries import projection as runs_projection
from starpulse.runs.model import opt_in
from starpulse.scheduler.adapters.exposition import autopilot_exposition
from starpulse.scheduler.adapters.remote import Remote
from starpulse.sessions import identity
from starpulse.sessions.adapters.outbound.session_start import starter
from starpulse.sessions.adapters.outbound.wake_metrics import metrics_of as wake_metrics_of
from starpulse.sweeper.publish import metrics_of as sweeper_metrics_of
from starpulse.views.adapters.inbound import tracing
from starpulse.views.adapters.inbound.asgi_app import page_app
from starpulse.views.adapters.inbound.page_server import DRAIN_S, PageServer
from starpulse.views.adapters.inbound.snapshots import Snapshots
from starpulse.views.adapters.outbound import skill_cost
from starpulse.views.adapters.outbound.gc_pauses import PAUSES, bound_full_collections
from starpulse.views.adapters.outbound.signal_folds import SignalFolds
from starpulse.views.adapters.outbound.storage_metrics import SCRAPE_CACHE_S, cached, docs_exposition, storage_exposition
from starpulse.views.adapters.outbound.take_over import command_take_over
from starpulse.views.bin.blocks import ApiConfig
from starpulse.views.ports.services import Services
lazy from starpulse.board.adapters.search import SearchIndex
lazy from starpulse.event_log.event_log import EventLog, bound_wal
lazy from starpulse.event_log.machine_store import MachineStore
lazy from starpulse.event_log.migrate import StoreNotMigrated
lazy from starpulse.event_log.opening import database_url
lazy from starpulse.event_log.readmodel.declared import declared_fields
lazy from starpulse.event_log.readmodel.read_model import ReadModel
lazy from starpulse.event_log.readmodel.snapshot_store import SnapshotStore
lazy from starpulse.pulls.adapters.outbound.github import GITHUB_MACHINES
lazy from starpulse.pulls.adapters.outbound.pulls import PullStore
lazy from starpulse.views.model.encoding import encode_snapshot


@dataclasses.dataclass(frozen=True)
class Host:
    """What the page needs from `starpulse.runtime`, the composition root that builds it: no context imports `runtime`,
    so `runtime` passes these in. `probes` is the live health probes, `contract` the doctor's reading of them, `readiness`
    the reader of `/api/health` over the log, the feed and the config."""

    config: Callable[..., ApiConfig]
    resolve_listen: Callable[..., None]
    prepare: Callable[..., tuple[Any, ...]]
    inherited_socket: Callable[[Any], socket.socket | None]
    listen: Callable[..., socket.socket]
    announce: Callable[..., None]
    announce_ready: Callable[[Any], None]
    assemble: Callable[..., tuple[Any, Any]]
    history_store: Callable[..., Any]
    contract: Callable[..., Any]
    readiness: Callable[..., Callable[[], dict[str, Any]]]
    github_metrics: Callable[..., Callable[[], str]]
    probes: Any
    static: Path
    listen_fd_env: str


def main(argv: list[str] | None, parser: argparse.ArgumentParser, *, host: Host) -> None:
    args = parser.parse_args(argv)
    config = host.config(parser, args.config)
    host.resolve_listen(args, config)
    ready = host.prepare(parser, args, config)
    try:
        listening = host.inherited_socket(os.environ)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    os.environ.pop(host.listen_fd_env, None)
    serve_page(parser, args, config, ready, listening or host.listen(parser, args), host=host)


def serve_page(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    config: ApiConfig,
    ready: tuple[Any, ...],
    listening: socket.socket,
    *,
    host: Host,
) -> None:
    """Build the Page API and serve it on `listening` until stopped: in the `starpulse worker api` child."""
    tracing.configure(os.environ)
    producer_tokens, opted_in = ready
    base = args.config.parent if args.config else Path.cwd()
    board_dir = base / str(config.board.get("path", DEFAULT_PATH))
    port = listening.getsockname()[1]
    # Every reader keeps its own cursor over the one event log, so a second copy on another port sees every entry too.
    # The declared --hours is the default; an override Admin wrote beside the config replaces it from the first snapshot.
    url = database_url(config.database_url, base)
    try:
        log = EventLog(url)
        # the page is drawn from the Task read model the projector folds, so no task file is read here
        model = ReadModel(log.engine, declared_fields(config.board))
        board, feed = host.assemble(config, base, args.hours * 3600, model)
    except (StoreNotMigrated, ValueError) as exc:
        parser.exit(os.EX_CONFIG, f"{exc}\n")  # `serve` stops on this status at the child's first run
    window = HistoryWindow(feed, args.hours, log)
    # the history dates the lanes the board adapter replays, so it is open before the adapter starts
    store = host.history_store(config, base, feed.machines)
    feed.record_lanes(store, log)
    feed.read_lanes(store.lane_rows)
    # the Board writer's projector indexes each task for search; this process only reads the index
    search = SearchIndex.open(log.engine, config.search)
    if search is not None:
        # the first search reads every vector (seconds of a GIL-bound worker); read them beside the start-up, never joined before ready
        threading.Thread(target=search.warm, name="search-warm", daemon=True).start()
    stop = StopEvent()
    bound_wal(log.engine, stop)  # the one process that checkpoints: a checkin in any worker runs none
    board.attach(log)
    feed.ready.set()
    # no follower runs in this process: what the workers keep in the log is applied when a request reads it (`CaughtUp`)
    caught_up = CaughtUp(log)
    # the Ledger a pull or run update changes is rebuilt here, so the request that applies the update never waits on it
    ledgers = ThreadPoolExecutor(1, thread_name_prefix="ledger")
    feed.build_ledgers_on(ledgers)
    # `starpulse worker board` keeps the claim refusals and verdicts as the deltas a stream replays
    saved_after = log.head() or 0  # before the store loads: a save between the two is announced past it
    pulls = PullStore(log.engine)
    caught_up.entries(SAVED_STREAM, refresh_on_save(pulls), saved_after)
    actor_metrics = None
    # `starpulse worker pulls` runs the context, as a child of this process or beside it; this process reads its
    # projection and asks it
    caught_up.state(PULLS_PROJECTION, Projected(log, feed).apply)
    # the analytics routes read the per-session folds of the signal table; the `signal-folds` context of
    # `starpulse worker contexts` keeps them current, so no fold runs in this process
    signal_folds = SignalFolds(log, feed.titled)
    # `starpulse worker runs` runs the run adapters and the pushed-runs follower; this process
    # draws the workflows that worker keeps in the log, and starts a run only when the page asks; an opt-in
    # worker's instance also shows the page whether that worker's process runs
    watched = {name: opt_in.Liveness(log, name) for name in opted_in}
    runs = runs_projection.Projected(log, feed, watched)
    caught_up.state(runs_projection.PROJECTION, runs.apply)
    if watched:
        caught_up.every_read(runs.refresh)  # a worker that exits announces nothing to the log
    if config.task_actor:
        actor_metrics = metrics_of(log)
    host.announce(port)

    cloudevents = (
        CloudEventsIngest(
            {p.name: p for p in config.producers}, producer_tokens, log, {**feed.machines, **GITHUB_MACHINES}
        )
        if producer_tokens
        else None
    )
    services = Services(
        machines=MachineStore(log.engine),
        harnesses=config.harnesses,
        views=config.views,
        start_session=starter(config.session_start_url),
        dispatch=dispatcher(log),
        entrypoint=config.session_harness().entrypoint,
        live=identity.current().live,
        events=cloudevents,
        scheduler=Remote(log),
        display=DisplaySettings(log),
        contract=lambda: host.contract(feed.contract_inputs(), config, host.probes),
        ready=host.readiness(log, feed, config),
        pulls=pulls,
        telemetry=signal_folds,
        search=search,
        analytics=config.analytics,
        take_over=command_take_over(config.take_over_command) if config.take_over_command else None,
        webhook=notice_webhook(cloudevents, config.webhook_producer, os.environ[config.webhook_token_env or ""])
        if config.webhook_producer and cloudevents
        else None,
        lanes=lambda: lane_surfaces(log.engine, config.board, base),
        scrape_cache_s=SCRAPE_CACHE_S,
        actor_metrics=actor_metrics,
        # the lane followers run in `starpulse worker contexts` and `conformance`; this process relays the metrics they keep
        lane_metrics=lane_metrics_of(log),
        autopilot_metrics=lambda: autopilot_exposition(log),
        storage_metrics=cached(
            lambda: storage_exposition(
                database=Path(sqlite_file) if (sqlite_file := make_url(url).database) else None,
                archive=base / config.event_log_archive_dir,
                board=board_dir,
            )
            + docs_exposition(board_dir, log.engine)
        ),
        sweeper_metrics=sweeper_metrics_of(log),
        bridge_metrics=lambda read=(bridge_metrics_of(log), wake_metrics_of(log)): "".join(part() for part in read),
        history_lag_metrics=history_lag_metrics_of(log),
        follower_lag_metrics=follower_lag_metrics_of(log, CHECKPOINT, STREAMS),
        skill_cost_metrics=skill_cost.metrics_of(log),
        child_cpu_metrics=child_cpu_metrics_of(log),
        follower_wake_metrics=follower_wake_metrics_of(log, tuple(CHILDREN)),
        github_metrics=cached(host.github_metrics(config, base), SCRAPE_CACHE_S),
    )
    snapshots = Snapshots(SnapshotStore(log.engine, encode_snapshot), log, stop)
    gc.callbacks.append(PAUSES.callback)
    bound_full_collections()
    app = page_app(feed, snapshots, host.static, store, window, board, services, caught_up=caught_up)
    try:
        httpd = PageServer(
            app,
            (args.host, args.port),
            listening,
            tls=config.tls,
            stopping=lambda: snapshots.announce("restarting", {"at": time.time()}),
            drain_s=DRAIN_S,
            serving=lambda: host.announce_ready(os.environ),
        )
        httpd.run()
    finally:
        stop.set()
        ledgers.shutdown(wait=True, cancel_futures=True)  # a running rebuild ends before the stores it reads close
        log.close()
        store.engine.dispose()
