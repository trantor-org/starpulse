"""`starpulse worker <context>`: one bounded context as its own process, beside `serve`.

`api` is the Page API, run by `starpulse.views.bin.api_worker` on the socket `serve` hands it; `pulls` is the Delivery context (the pull request store's projection from the machine events and its manual refresh, the task actor and the release of
dependents); `scheduler` is the Scheduler context, run by `starpulse.scheduler.bin.scheduler_worker`; `runs` is the
Runs context, run by `starpulse.runs.bin.runs_worker`; `github-actions`, `systemd`, `temporal` and `woodpecker` are the run Adapters, each run by `serve`'s `contexts` child for the `[[runs]]` instances that name it, run by
`starpulse.runs.bin.adapter_worker`; `flow-metrics` is the Flow Metrics context, run by
`starpulse.flow_metrics.bin.flow_metrics_worker`; `search` is the Search context's embedding catch-up, run by
`starpulse.board.bin.search_worker`; `board` is the Board context's writer (the Start Criteria dating), run by `starpulse.board.bin.board_worker`;
`sweeper` is the one leased sweeper, run by `starpulse.sweeper.bin.sweeper_worker`;
`contexts` runs every one of those but `api` as threads of this one process (`starpulse.runtime.contexts`).

`pulls` is run by `starpulse.pulls.bin.pulls_worker`. This module is the composition root of the workers: it builds the
collaborators a worker needs (`runtime.assembly`, `runtime.hold`, `runtime.wiring`) and hands them to its `main`, as no
context imports `runtime`.
"""

import argparse
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starpulse.event_log.wake import StopEvent
from starpulse.runtime.listen import listen_options
lazy from starpulse.runtime.config import rehearsing
lazy from starpulse.runtime.contexts import contexts_of
lazy from starpulse.runtime.hold import BOOT_ENV
lazy from starpulse.runtime.readiness import readiness

logger = logging.getLogger(__name__)

#: The run Adapters that run as their own workers (`starpulse.runs.bin.adapter_worker`): `serve`'s `contexts` child runs one as a thread for each that a `[[runs]]` instance names.
OPT_IN = ("github-actions", "systemd", "woodpecker")
CONTEXTS = ("api", "pulls", "scheduler", "runs", "flow-metrics", "search", "board", "sweeper", *OPT_IN, "contexts", "conformance")


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


def _readiness(log: Any, feed: Any, config: Any) -> Callable[[], dict[str, Any]]:
    """The reader of `/api/health` over the contexts `config` makes `serve` supervise and the boot token it handed them."""

    return readiness(log, feed, [*contexts_of(config), *([] if rehearsing() else ["pulls"])], os.environ.get(BOOT_ENV))


def main(argv: list[str] | None = None) -> None:
    """Run the worker `argv` names. Each bin is imported only for its own context: the other workers' closures hold no
    page, scheduler or run adapter module."""
    logging.basicConfig(level=logging.INFO)
    parser = worker_parser()
    args = parser.parse_args(argv)
    if args.context == "api":
        from starpulse.cli import doctor
        from starpulse.runtime import listen, sched, wiring
        from starpulse.runtime.assembly import assemble, github_metrics, history_store
        from starpulse.runtime.hold import LISTEN_FD_ENV, announce_ready
        from starpulse.views.bin import api_worker

        sched.shorten_slice()  # before the page-server and request-worker threads start, which inherit it
        host = api_worker.Host(
            config=wiring.read_config,
            resolve_listen=listen.resolve_listen,
            prepare=wiring.prepare,
            inherited_socket=listen.inherited_socket,
            listen=listen.listen,
            announce=wiring.announce,
            announce_ready=announce_ready,
            assemble=assemble,
            history_store=history_store,
            contract=doctor.contract,
            readiness=_readiness,
            github_metrics=github_metrics,
            probes=doctor.LIVE,
            static=wiring.STATIC,
            listen_fd_env=LISTEN_FD_ENV,
        )
        return api_worker.main(argv, parser, host=host)
    from starpulse.runtime.assembly import history_store, own_pull_merged, scheduler_board, worker_board
    from starpulse.runtime.config import discover, load
    from starpulse.runtime.hold import BOOT_ENV, hold

    # each context's bin reads its section of the root config, which only the runtime loads
    loader = {"discover": discover, "load": load}

    if args.context in ("contexts", "conformance"):
        from starpulse.runtime.contexts import contexts_of, run_contexts
        from starpulse.runtime.hold import announce_ready, go_event

        path = discover(args.config)
        try:
            config = load(path)
            base = args.config.parent if args.config else Path.cwd()
            names = contexts_of(config) if args.context == "contexts" else ["conformance"]
            return run_contexts(
                config, path, names, StopEvent(), base=base, child=args.context,
                go=go_event(os.environ), prepared=lambda: announce_ready(os.environ),
            )  # fmt: skip
        except (OSError, ValueError) as exc:
            parser.exit(1, f"{path}: {exc}\n")
    if args.context == "scheduler":
        from starpulse.bridge.account_room import account_room
        from starpulse.scheduler.bin import scheduler_worker
        from starpulse.sessions.adapters.outbound.claude_code_notify import end_with
        from starpulse.sessions.adapters.outbound.session_start import starter

        return scheduler_worker.main(
            argv,
            parser,
            **loader,
            worker_board=scheduler_board,
            hold=hold,
            starter=starter,
            delivered=own_pull_merged,
            ender=end_with,
            rooms=account_room,
        )
    if args.context == "runs":
        from starpulse.runs.bin import runs_worker
        from starpulse.runtime.wiring import run_adapters

        return runs_worker.main(
            argv,
            parser,
            **loader,
            run_adapters=run_adapters,
            worker_board=worker_board,
            history_store=history_store,
            hold=hold,
        )
    if (
        args.context in OPT_IN
    ):  # a run adapter's worker: the `contexts` child runs it, the runs worker leaves it its instances
        from starpulse.runs.bin import adapter_worker
        from starpulse.runtime.wiring import run_adapters

        return adapter_worker.main(
            argv, parser, args.context, **loader, run_adapters=run_adapters, worker_board=worker_board, hold=hold
        )
    if args.context == "flow-metrics":
        from starpulse.flow_metrics.bin import flow_metrics_worker
        from starpulse.runtime.assembly import declared

        return flow_metrics_worker.main(
            argv,
            parser,
            **loader,
            declared=declared,
            history_store=history_store,
            hold=hold,
        )
    if args.context == "sweeper":
        from starpulse.runtime.assembly import github_kinds, prune_steps
        from starpulse.sweeper.bin import sweeper_worker

        def contexts(log, parser, config):
            return github_kinds(config, log)

        return sweeper_worker.main(argv, parser, **loader, prune=prune_steps, contexts=contexts, hold=hold)
    if args.context == "search":
        from starpulse.board.bin import search_worker

        return search_worker.main(argv, parser, **loader, hold=hold)
    if args.context == "board":
        from starpulse.board.bin import board_worker
        from starpulse.runtime.assembly import assemble
        from starpulse.runtime.read_model_follow import follow
        from starpulse.runtime.store_refold import spawn
        from starpulse.runtime.wiring import run_adapters
        from starpulse.runtime.writer_followers import feed_followers

        return board_worker.main(
            argv, parser, **loader, assemble=assemble, history_store=history_store, follow=follow,
            followers=lambda parser, config: feed_followers(run_adapters(parser, config)), hold=hold, refold=spawn,
        )  # fmt: skip
    from starpulse.event_log.child_cpu import keep_process
    from starpulse.pulls.bin import pulls_worker
    from starpulse.runtime.delivery_wiring import start_delivery
    from starpulse.runtime.hold import announce_ready, go_event
    from starpulse.runtime.readiness import stamp

    def started(log):
        if boot := os.environ.get(BOOT_ENV):
            stamp(log, "pulls", boot)

    return pulls_worker.main(
        argv,
        parser,
        **loader,
        worker_board=worker_board,
        history_store=history_store,
        start_delivery=start_delivery,
        hold=hold,
        go=go_event(os.environ),
        prepared=lambda: announce_ready(os.environ),
        kept=lambda log: keep_process(log, "pulls"),
        started=started,
    )
