"""`starpulse worker contexts`: the background contexts as threads of one process over one replica.

Each context (Board, Delivery, Scheduler, Runs, Flow Metrics, Search and the run Adapters) keeps the `start` its own
`starpulse worker <context>` process runs; here each runs on a thread named `ctx-<name>` over one event log, one board
and one read-model fold, where `serve` today supervises a process for each (spec doc-1054, D1 and D2).

A context whose `start` raises is stopped, waits a growing backoff and starts again on its own thread, while every other
context's thread stays. A context that hangs, or whose loop dies after `start` returned, is not restarted. `SIGTERM`
stops every context; `SIGHUP` reloads each one that started.

This module is part of the composition root (`starpulse.runtime`): it imports each bin lazily, as no context imports
`runtime`.
"""

from __future__ import annotations

import argparse
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from starpulse.board.model.adapter_types import ADAPTER_CONTEXTS
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.runtime.config import Config

logger = logging.getLogger(__name__)

#: Starts one context on the stop event it is given and returns its reload.
Starter = Callable[[threading.Event], Callable[[], None]]

#: The first and the longest wait, in seconds, before a context whose start raised starts again; each wait doubles.
BACKOFF_S = (1.0, 30.0)

_JOIN_S = 5.0


def contexts_of(config: Config) -> list[str]:
    """The contexts this process runs for `config`: those `serve` supervises except the Page API (it holds the page's
    socket), Search only with an `embeddings_url`, then the run Adapters its `[[runs]]` instances name."""
    from starpulse.runtime.supervisor import WORKER_CONTEXTS, adapter_contexts

    kept = [c for c in WORKER_CONTEXTS if c != "api" and (c != "search" or config.search.embeddings_url)]
    return [*kept, *adapter_contexts(config)]


class _Refusing(argparse.ArgumentParser):
    """The parser `run_adapters` reports a bad runs instance to: it raises where a worker's parser would exit."""

    def exit(self, status: int = 0, message: str | None = None) -> Any:
        raise ValueError((message or "").strip())


class _SharedBoard:
    """The one board and feed of the process: the Board context's when it runs here, otherwise built on first use."""

    def __init__(self, names: Sequence[str], build: Callable[[], tuple[Any, Any]], stop: threading.Event) -> None:
        self._owned = "board" in names
        self._build = build
        self._stop = stop
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._built: tuple[Any, Any] | None = None

    def publish(self, board: Any, feed: Any) -> None:
        self._built = (board, feed)
        self._ready.set()

    def get(self) -> tuple[Any, Any]:
        """The board and feed, waiting for the Board context to publish them; raises when the process stops first."""
        if not self._owned:
            with self._lock:
                if self._built is None:
                    self.publish(*self._build())
        while not self._ready.wait(0.1):
            if self._stop.is_set():
                raise RuntimeError("stopped before the board was built")
        assert self._built is not None
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


def default_starters(
    config: Config, path: Path | None, base: Path, log: EventLog, names: Sequence[str], stop: threading.Event
) -> dict[str, Starter]:
    """The starter of each context in `names`, all over `log` and one board. Raises `ValueError` for a name that is no
    context or a `[[runs]]` instance whose adapter the config cannot load."""
    from starpulse.runtime.assembly import assemble, keep_event_log, own_pull_merged, worker_board
    from starpulse.runtime.assembly import history_store as build_history_store
    from starpulse.runtime.config import load
    from starpulse.runtime.read_model_follow import follow

    history_store = _SharedStore(build_history_store)
    shared = _SharedBoard(names, lambda: worker_board(config, base, log, stop), stop)
    adapters: Sequence[Any] = []
    if "runs" in names or any(name in names for name in ADAPTER_CONTEXTS):
        from starpulse.runtime.server import run_adapters

        adapters = run_adapters(_Refusing(), config)

    def board(own: threading.Event) -> Callable[[], None]:
        from starpulse.board.bin import board_worker

        return board_worker.start(
            config, path, base, log, own, load=load, assemble=assemble, history_store=history_store, follow=follow,
            ready=shared.publish,
        )  # fmt: skip

    def pulls(own: threading.Event) -> Callable[[], None]:
        from starpulse.pulls.bin import pulls_worker
        from starpulse.runtime.server import start_delivery

        return pulls_worker.start(
            config, path, base, log, own, load=load, worker_board=shared, history_store=history_store,
            start_delivery=start_delivery,
        )  # fmt: skip

    def scheduler(own: threading.Event) -> Callable[[], None]:
        from starpulse.runtime.server import _cached, trajectories_response
        from starpulse.scheduler.bin import scheduler_worker
        from starpulse.sessions.session_start import starter

        return scheduler_worker.start(
            config, path, base, log, own, load=load, worker_board=shared, history_store=history_store,
            trajectories_response=trajectories_response, cached=_cached, starter=starter, delivered=own_pull_merged,
        )  # fmt: skip

    def runs(own: threading.Event) -> Callable[[], None]:
        from starpulse.runs import opt_in
        from starpulse.runs.bin import runs_worker

        return runs_worker.start(
            config, path, base, log, own, load=load, adapters=opt_in.followed_by(adapters, None), worker_board=shared,
            history_store=history_store,
        )  # fmt: skip

    def adapter(name: str) -> Starter:
        def start(own: threading.Event) -> Callable[[], None]:
            from starpulse.runs import opt_in
            from starpulse.runs.bin import adapter_worker

            return adapter_worker.start(
                config, path, base, log, own, load=load, worker_board=shared,
                adapters=opt_in.followed_by(adapters, name),
            )  # fmt: skip

        return start

    def flow_metrics(own: threading.Event) -> Callable[[], None]:
        from starpulse.flow_metrics.bin import flow_metrics_worker

        return flow_metrics_worker.start(
            config, path, base, log, own, load=load, assemble=shared, history_store=history_store,
            keep_event_log=keep_event_log,
        )  # fmt: skip

    def search(own: threading.Event) -> Callable[[], None]:
        from starpulse.board.bin import search_worker

        return search_worker.start(config, path, base, log, own, load=load)

    known: dict[str, Starter] = {
        "board": board, "pulls": pulls, "scheduler": scheduler, "runs": runs, "flow-metrics": flow_metrics,
        "search": search, **{name: adapter(name) for name in ADAPTER_CONTEXTS},
    }  # fmt: skip
    unknown = [name for name in names if name not in known]
    if unknown:
        raise ValueError(f"no such context: {', '.join(unknown)}")
    return {name: known[name] for name in names}


def _keep(
    name: str,
    starter: Starter,
    stop: threading.Event,
    reloads: dict[str, Callable[[], None]],
    stops: dict[str, threading.Event],
    backoff: tuple[float, float],
) -> None:
    """Start the context on its own stop event, again after a growing wait each time `starter` raises, then hold the
    thread until the process stops. A failed start's stop event is set, so what it began before raising ends."""
    wait = backoff[0]
    while not stop.is_set():
        own = threading.Event()
        stops[name] = own
        try:
            reloads[name] = starter(own)
        except Exception:
            logger.exception("%s: start failed; starting again in %.1f s", name, wait)
            own.set()
            if stop.wait(wait):
                return
            wait = min(wait * 2, backoff[1])
            continue
        logger.info("%s: started", name)
        stop.wait()
        own.set()
        return


def run_contexts(
    config: Config,
    path: Path | None,
    names: Sequence[str],
    stop: threading.Event,
    *,
    base: Path | None = None,
    starters: Mapping[str, Starter] | None = None,
    hold: Callable[[threading.Event, Callable[[], None]], None] | None = None,
    backoff: tuple[float, float] = BACKOFF_S,
) -> None:
    """Run each context of `names` on a `ctx-<name>` thread until `stop` is set, and return once they are told to end.

    `starters` replaces the real starters (tests); `hold` is the wait for `SIGTERM` and `SIGHUP` (`runtime.hold`).
    Raises `ValueError` before any thread starts when a name is no context or a runs adapter cannot load."""
    base = base or (path.parent if path else Path.cwd())
    if starters is None:
        log = EventLog(database_url(config.database_url, base))
        starters = default_starters(config, path, base, log, names, stop)
    if hold is None:
        from starpulse.runtime.hold import hold
    reloads: dict[str, Callable[[], None]] = {}
    stops: dict[str, threading.Event] = {}
    threads = [
        threading.Thread(
            target=_keep, args=(name, starters[name], stop, reloads, stops, backoff), name=f"ctx-{name}", daemon=True
        )
        for name in names
    ]
    for thread in threads:
        thread.start()

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
        for own in list(stops.values()):
            own.set()
        for thread in threads:
            thread.join(_JOIN_S)
