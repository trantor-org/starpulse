"""`starpulse worker api`: the Page API as its own process, a child `serve` supervises.

`serve` binds the listening socket and hands it to this child on the descriptor `STARPULSE_LISTEN_FD` names
(`Host.listen_fd_env`), so a connection made while the child is being replaced waits in the
socket's backlog for the next one rather than being refused. The child builds the page as `serve` once did: it reads the
Board from the replica the Board child publishes and starts no adapter watcher. Started by hand, without a handed
socket, it binds `--host` and `--port` itself.

`SIGTERM` finishes the requests it took (`serve_until_stopped`) and saves the Board it keeps; a config change replaces
the process, as the page is built from the whole config once.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starpulse._internal.config.config import Config
from starpulse.board.adapters.history_window import SETTINGS_FILE, HistoryWindow
from starpulse.board.claim_refusals import CLAIMS_STREAM
from starpulse.event_log import events as machine_events
from starpulse.event_log import lane_events
from starpulse.event_log.conformance_monitor import Conformance
from starpulse.harness_telemetry.telemetry import TelemetryLog
from starpulse.pulls.delivery import Projected, follow_saves, metrics_of, poller_problem, request_refresh
from starpulse.pulls.pull_refresh import PullRefresh
from starpulse.pulls.pull_store import PullSync
from starpulse.runs import opt_in
from starpulse.runs import projection as runs_projection
from starpulse.runs.cloudevents import CloudEventsIngest
from starpulse.sessions.session_start import starter
from starpulse.views.asgi_app import _CONTRACT_TTL_S, _cached, page_app
from starpulse.views.page_server import DRAIN_S, PageServer
from starpulse.views.services import Services
from starpulse.views.take_over import temporal_take_over


@dataclasses.dataclass(frozen=True)
class Host:
    """What the page needs from `starpulse.runtime`, the composition root that builds it: no context imports `runtime`,
    so `runtime` passes these in. `probes` is the live health probes, `contract` the doctor's reading of them."""

    config: Callable[..., Config]
    prepare: Callable[..., tuple[Any, ...]]
    inherited_socket: Callable[[Any], socket.socket | None]
    listen: Callable[..., socket.socket]
    announce: Callable[..., None]
    scheduler_remote: Callable[..., Any]
    serve_until_stopped: Callable[..., None]
    announce_ready: Callable[[Any], None]
    assemble: Callable[..., tuple[Any, Any]]
    history_store: Callable[..., Any]
    follow_read_model: Callable[..., object]
    contract: Callable[..., Any]
    probes: Any
    static: Path
    listen_fd_env: str


def main(argv: list[str] | None, parser: argparse.ArgumentParser, *, host: Host) -> None:
    args = parser.parse_args(argv)
    config = host.config(parser, args.config)
    ready = host.prepare(parser, args, config)
    try:
        listening = host.inherited_socket(os.environ)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    os.environ.pop(host.listen_fd_env, None)
    serve_page(parser, args, config, ready, listening or host.listen(parser, args), host=host)


def serve_page(  # pragma: no mutate block — serve_forever process boundary
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    config: Config,
    ready: tuple[Any, ...],
    listening: socket.socket,
    *,
    host: Host,
) -> None:
    """Build the Page API and serve it on `listening` until stopped: in the `starpulse worker api` child."""

    from starpulse.board.adapters import replica  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse.board.adapters.search import SearchIndex  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse.board.board_feed import follow  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse.board.claim_refusals import ClaimRefusals  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse.board.machine_tasks import MachineTasks  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse.event_log.event_log import EventLog  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse.event_log.opening import database_url  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse.event_log.readmodel.declared import declared_fields  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse.event_log.readmodel.projector import Projector  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse.event_log.readmodel.read_model import ReadModel  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse.event_log.store import EventStore  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse.pulls.pulls import PullStore  # noqa: PLC0415 - the database stack loads after the config is accepted

    refresh_token, starts, reruns, run_safe, producer_tokens, opted_in = ready
    base = args.config.parent if args.config else Path.cwd()
    port = listening.getsockname()[1]
    # Every reader keeps its own cursor over the one event log, so a second copy on another port sees every entry too.
    # The declared --hours is the default; an override Admin wrote beside the config replaces it from the first snapshot.
    url = database_url(config.database_url, base)
    log = EventLog(url)
    # `read_model`: the page is drawn from the Task read model the projector folds, so no task file is read here
    model = ReadModel(log.engine, declared_fields(config.board)) if config.read_model else None
    try:
        board, feed = host.assemble(config, base, args.hours * 3600, run_safe, model)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    window = HistoryWindow(feed, args.hours, log, base / SETTINGS_FILE)
    # the history dates the lanes the board adapter replays, so it is open before the adapter starts
    store = host.history_store(config, base, feed.machines)
    feed.date_lanes(store.lane_path)
    feed.record_lanes(store)
    feed.record_ratings(log)
    # `starpulse worker board` dates when each task's Start Criteria were met; this process rereads the dates it keeps.
    threading.Thread(
        target=feed.follow_criteria, args=(store, threading.Event()), name="criteria-follow", daemon=True
    ).start()
    if model is not None:  # under `read_model` the board worker sweeps and saves each pass's expiries; serve follows them
        threading.Thread(
            target=feed.follow_expiries, args=(store, threading.Event()), name="expiries-follow", daemon=True
        ).start()
    feed.read_lanes(store.lane_rows)
    # the instance indexes its board for search
    search = SearchIndex.open(log.engine, config.search)
    if search is not None:
        feed.index_tasks(search)  # `starpulse worker search` catches the vectors up off the feed's path
    stop = threading.Event()
    if model is None:
        replica.read(board, feed, f"starpulse-{port}", log, config, stop)
    else:
        if board.attach is not None:
            board.attach(log)
        # `starpulse worker board` folds the events when it runs; otherwise this process does
        projector = None if config.board_worker else Projector(log.engine, EventStore(log.engine), search)
        if projector is not None:
            projector.catch_up()
        feed.follow_read_model()
        feed.ready.set()
        host.follow_read_model(projector, feed, stop)
    tasks = MachineTasks(feed, board.keys)
    follow(tasks, log, machine_events.STREAM, tasks.handle_entry)
    refusals = ClaimRefusals(feed)
    follow(refusals, log, CLAIMS_STREAM, refusals.handle_entry)
    saved_after = log.head() or 0  # before the store loads: a save between the two is announced past it
    pulls = PullStore(log.engine)
    follow_saves(pulls, log, stop, saved_after)
    pull_refresh = None
    actor_metrics = None
    # `starpulse worker pulls` runs the context, as a child of this process or beside it; this process reads its
    # projection and asks it
    Projected(log, feed).follow(stop)
    # a lane move any writer leaves unnamed is counted
    unattributed = lane_events.Unattributed()
    unattributed.follow(log, stop)
    # a move no transition of its machine declares is counted per machine
    conformance = Conformance(feed.machines)
    conformance.follow(log, stop)
    # `starpulse worker runs` runs the run adapters and the pushed-runs follower; this process
    # draws the workflows that worker keeps in the log, and starts a run only when the page asks; an opt-in
    # worker's instance also shows the page whether that worker is beating
    watched = {name: opt_in.problem(log, name) for name in opted_in}
    runs_projection.Projected(log, feed, watched).follow(stop)
    if config.task_actor:
        actor_metrics = metrics_of(log)
    probes = dataclasses.replace(host.probes, poller=poller_problem(log))
    if refresh_token:
        pull_refresh = PullRefresh(refresh_token, request_refresh(log, PullSync(pulls, feed, config.repos).tracked))
    host.announce(port, feed.snapshot()["hint"])
    scheduler_stop = threading.Event()
    scheduler_runtime = host.scheduler_remote(config, base, feed, log, scheduler_stop)
    from starpulse.pulls.github import GITHUB_MACHINES  # noqa: PLC0415 - the database stack loads after the config is accepted

    cloudevents = (
        CloudEventsIngest(
            {p.name: p for p in config.producers}, producer_tokens, log, {**feed.machines, **GITHUB_MACHINES}
        )
        if producer_tokens
        else None
    )
    services = Services(
        starts=starts,
        run_safe=run_safe,
        reruns=reruns,
        harnesses=config.harnesses,
        start_session=starter(config.session_start_url),
        events=cloudevents,
        scheduler=scheduler_runtime,
        contract=_cached(lambda: host.contract(feed.snapshot(), config, probes), _CONTRACT_TTL_S),
        pulls=pulls,
        telemetry=TelemetryLog(log),
        search=search,
        analytics=config.analytics,
        pull_refresh=pull_refresh,
        take_over=temporal_take_over(config.temporal_address) if config.temporal_address else None,
        slow_read_s=config.slow_read_seconds,
        actor_metrics=actor_metrics,
        lane_metrics=unattributed.exposition,
        conformance_metrics=conformance.exposition,
    )
    app = page_app(feed, host.static, store, window, board, services)
    try:
        httpd = PageServer(
            app,
            (args.host, args.port),
            listening,
            tls=config.tls,
            stopping=lambda: feed.announce("restarting", {"at": time.time()}),
            drain_s=DRAIN_S,
        )
        host.announce_ready(os.environ)
        host.serve_until_stopped(httpd, feed)
    finally:
        scheduler_stop.set()
        log.close()
        store.engine.dispose()
