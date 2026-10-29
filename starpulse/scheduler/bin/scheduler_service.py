"""The scheduler's runtime started over a board: the sampler and the dispatch loop, on daemon threads.

`starpulse worker scheduler` starts it as its own process (`starpulse.scheduler.bin.scheduler_worker`), a child `serve` supervises. It is not
imported at the top of `starpulse.runtime.server`, so the Delivery worker's import closure holds no scheduler module.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Board, Written
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.adapters.outbound.history import History
from starpulse.flow_metrics.model.level import Level
from starpulse.scheduler.adapters.runtime import Runtime
from starpulse.scheduler.adapters.runtime import build as build_scheduler
from starpulse.scheduler.adapters.starter import builtin_starter
from starpulse.scheduler.bin.blocks import SchedulerConfig
from starpulse.scheduler.model.admission import ranks_from_trajectories_body

#: How long the dispatch loop holds the trajectory chain it ranks on: the analytics read the whole history.
_CHAIN_TTL_S = 300


def start_scheduler(
    config: SchedulerConfig,
    base: Path,
    feed: BoardFeed,
    board: Board,
    history: History,
    log: EventLog,
    level: Level | None,
    stop: threading.Event,
    probe: Callable[[], Mapping[str, float]] | None = None,
    publish: Callable[[str, dict[str, Any]], None] | None = None,
    *,
    trajectories_response: Callable[..., tuple[bytes, int]],
    cached: Callable[[Callable[[], dict[str, Any]], float], Callable[[], dict[str, Any]]],
    starter: Callable[..., Any],
    delivered: Callable[[EventLog, Mapping[str, Any]], bool],
) -> Runtime:
    """The scheduler's runtime with its sampler and dispatch loop running on daemon threads until `stop` is set.

    The loop admits from the lane `[scheduler] lane` names (else the board's initial lane), starts a session through
    `session_start_url` (else the built-in tmux starter in `base`), and settles a stuck one by moving it to Needs
    attention through the board's editor. Its chain and per-task P(goal) are the trajectory analytics' when this
    server has a `[level]` table. `runtime` passes `trajectories_response`, `cached`, `starter` and `delivered`, as no context imports it.
    """

    def settle(task: str, reason: str) -> Written:
        if board.edit is None:
            return Written(False, "this board has no editor", unavailable=True)
        if board.roles.attention is None:
            return Written(False, "this board's machine has no lane that waits on a person", unavailable=True)
        return board.edit(task, {"status": board.roles.attention}, reason)

    def claim(task: str, comment: str) -> Written:
        if board.edit is None:
            return Written(False, "this board has no editor", unavailable=True)
        return board.edit(task, {}, comment)

    def merged(agent: Mapping[str, Any]) -> bool:
        return delivered(log, agent)

    initial = next(state["id"] for state in feed.machines["board"]["states"] if state.get("initial"))
    lane = config.scheduler.eligible_lane(initial)

    def read_ranks() -> dict[str, Any]:
        empty: dict[str, Any] = {"chain": {}, "p_goals": {}}
        if level is None:
            return empty
        query: dict[str, list[str]] = {}
        body, status = trajectories_response(history, query, level, feed.machines, time.time())
        if status == 400:
            history_s = json.loads(body).get("history_s")
            if history_s:
                query = {"hours": [str(float(history_s) / 3600)]}
                body, status = trajectories_response(history, query, level, feed.machines, time.time())
        if status != 200:
            return empty
        return ranks_from_trajectories_body(json.loads(body), lane)

    ranks = cached(read_ranks, _CHAIN_TTL_S)
    runtime = build_scheduler(
        config.scheduler,
        log,
        feed,
        probe,
        start=starter(config.session_start_url, by="scheduler") or builtin_starter(base),
        settle=settle,
        claim=claim,
        merged=merged,
        chain=lambda: ranks()["chain"],
        p_goals=lambda: ranks()["p_goals"],
        lane=lane,
    )
    runtime.wire_status(publish or feed.publish)
    threading.Thread(target=runtime.sampler.run_forever, args=(stop,), name="scheduler-sampler", daemon=True).start()
    if runtime.loop is not None:
        threading.Thread(target=runtime.loop.run_forever, args=(stop,), name="scheduler-loop", daemon=True).start()
    return runtime
