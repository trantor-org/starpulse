"""`starpulse worker <context>`: one bounded context as its own process, beside `serve`.

`api` is the Page API, run by `starpulse.views.bin.api_worker` on the socket `serve` hands it; `pulls` is the Delivery context (the pull request store's projection from the machine events and its manual refresh, the task actor and the release of
dependents); `scheduler` is the Scheduler context, run by `starpulse.scheduler.bin.scheduler_worker`; `runs` is the
Runs context, run by `starpulse.runs.bin.runs_worker`; `dagu`, `github-actions` and `systemd` are the run Adapters, each supervised by `serve` for the `[[runs]]` instances that name it, run by
`starpulse.runs.bin.adapter_worker`; `flow-metrics` is the Flow Metrics context, run by
`starpulse.flow_metrics.bin.flow_metrics_worker`; `search` is the Search context's embedding catch-up, run by
`starpulse.board.bin.search_worker`; `board` is the Board context's writer (the Start Criteria dating), run by `starpulse.board.bin.board_worker`.

`pulls` is run by `starpulse.pulls.bin.pulls_worker`. This module is the composition root of the workers: it builds the
collaborators a worker needs (`runtime.assembly`, `runtime.hold`, `runtime.server`) and hands them to its `main`, as no
context imports `runtime`.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from starpulse.runtime.server import listen_options

logger = logging.getLogger(__name__)

#: The run Adapters that run as their own workers (`starpulse.runs.bin.adapter_worker`): `serve` supervises one for each that a `[[runs]]` instance names.
OPT_IN = ("dagu", "github-actions", "systemd")
CONTEXTS = ("api", "pulls", "scheduler", "runs", "flow-metrics", "search", "board", *OPT_IN)


def worker_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="starpulse worker", description="Run one bounded context of StarPulse as its own process."
    )
    parser.add_argument(
        "context",
        choices=CONTEXTS,
        help="the bounded context to run",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="the config `serve` runs from; default: starpulse.toml in the working directory, else the defaults",
    )
    listen_options(parser)  # read by `api`: where the page listens when `serve` hands it no socket
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run the worker `argv` names. Each bin is imported only for its own context: the other workers' closures hold no
    page, scheduler or run adapter module."""
    logging.basicConfig(level=logging.INFO)
    parser = worker_parser()
    args = parser.parse_args(argv)
    if args.context == "api":
        from starpulse.cli import doctor
        from starpulse.runtime import read_model_follow, server
        from starpulse.runtime.assembly import assemble, history_store
        from starpulse.runtime.hold import LISTEN_FD_ENV, STATIC_ENV, announce_ready
        from starpulse.views.bin import api_worker

        if static := os.environ.get(STATIC_ENV):
            server._STATIC = Path(static)  # the page build `serve` checked, which `prepare` and the page app read
        host = api_worker.Host(
            config=server._config,
            resolve_listen=server.resolve_listen,
            prepare=server.prepare,
            inherited_socket=server.inherited_socket,
            listen=server.listen,
            announce=server.announce,
            scheduler_remote=server.scheduler_remote,
            serve_until_stopped=server.serve_until_stopped,
            announce_ready=announce_ready,
            assemble=assemble,
            history_store=history_store,
            follow_read_model=read_model_follow.follow,
            contract=doctor.contract,
            probes=doctor.LIVE,
            static=server._STATIC,
            listen_fd_env=LISTEN_FD_ENV,
        )
        return api_worker.main(argv, parser, host=host)
    from starpulse.runtime.assembly import history_store, worker_board
    from starpulse.runtime.config import discover, load
    from starpulse.runtime.hold import hold

    # each context's bin reads its section of the root config, which only the runtime loads (spec doc-966, D6)
    loader = {"discover": discover, "load": load}

    if args.context == "scheduler":
        from starpulse.runtime.server import _cached, trajectories_response
        from starpulse.scheduler.bin import scheduler_worker
        from starpulse.sessions.session_start import starter

        return scheduler_worker.main(
            argv,
            parser,
            **loader,
            worker_board=worker_board,
            history_store=history_store,
            hold=hold,
            trajectories_response=trajectories_response,
            cached=_cached,
            starter=starter,
        )
    if args.context == "runs":
        from starpulse.runs.bin import runs_worker
        from starpulse.runtime.server import run_adapters

        return runs_worker.main(
            argv,
            parser,
            **loader,
            run_adapters=run_adapters,
            worker_board=worker_board,
            history_store=history_store,
            hold=hold,
        )
    if args.context in OPT_IN:  # a run adapter's worker: `serve` supervises it, the runs worker leaves it its instances
        from starpulse.runs.bin import adapter_worker
        from starpulse.runtime.server import run_adapters

        return adapter_worker.main(
            argv, parser, args.context, **loader, run_adapters=run_adapters, worker_board=worker_board, hold=hold
        )
    if args.context == "flow-metrics":
        from starpulse.flow_metrics.bin import flow_metrics_worker
        from starpulse.runtime.assembly import assemble, keep_event_log

        return flow_metrics_worker.main(
            argv,
            parser,
            **loader,
            assemble=assemble,
            history_store=history_store,
            keep_event_log=keep_event_log,
            hold=hold,
        )
    if args.context == "search":
        from starpulse.board.bin import search_worker

        return search_worker.main(argv, parser, **loader, hold=hold)
    if args.context == "board":
        from starpulse.board.bin import board_worker
        from starpulse.runtime.assembly import assemble
        from starpulse.runtime.read_model_follow import follow

        return board_worker.main(
            argv, parser, **loader, assemble=assemble, history_store=history_store, follow=follow, hold=hold
        )
    from starpulse.pulls.bin import pulls_worker
    from starpulse.runtime.server import start_delivery

    return pulls_worker.main(
        argv,
        parser,
        **loader,
        worker_board=worker_board,
        history_store=history_store,
        start_delivery=start_delivery,
        hold=hold,
    )
