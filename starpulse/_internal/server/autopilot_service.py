"""The autopilot's runtime started over a board: the sampler and the dispatch loop, on daemon threads.

`starpulse worker autopilot` starts it as its own process (`server.autopilot_worker`), a child `serve` supervises. It is not
imported at the top of `server.server`, so the Delivery worker's import closure holds no autopilot module.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from starpulse._internal.autopilot.admission import ranks_from_trajectories_body
from starpulse._internal.autopilot.runtime import Runtime
from starpulse._internal.autopilot.runtime import build as build_autopilot
from starpulse._internal.autopilot.starter import builtin_starter
from starpulse._internal.board.seam import Board, Written
from starpulse._internal.config.config import Config
from starpulse._internal.config.level import Level
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import History
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.harnesses.session_start import starter
from starpulse._internal.server.server import _cached, trajectories_response

#: How long the dispatch loop holds the trajectory chain it ranks on: the analytics read the whole history.
_CHAIN_TTL_S = 300


def start_autopilot(
    config: Config,
    base: Path,
    feed: BoardFeed,
    board: Board,
    history: History,
    log: EventLog,
    level: Level | None,
    stop: threading.Event,
    probe: Callable[[], Mapping[str, float]] | None = None,
    publish: Callable[[str, dict[str, Any]], None] | None = None,
) -> Runtime:
    """The autopilot's runtime with its sampler and dispatch loop running on daemon threads until `stop` is set.

    The loop admits from the lane `[autopilot] lane` names (else the board's initial lane), starts a session through
    `session_start_url` (else the built-in tmux starter in `base`), and settles a stuck one by moving it to Needs
    attention through the board's editor. Its chain and per-task P(goal) are the trajectory analytics' when this
    server has a `[level]` table, including on an IC instance that is not serving `--hub`.
    """

    def settle(task: str, reason: str) -> Written:
        if board.edit is None:
            return Written(False, "this board has no editor", unavailable=True)
        return board.edit(task, {"status": "needs_attention"}, reason)

    def claim(task: str, comment: str) -> Written:
        if board.edit is None:
            return Written(False, "this board has no editor", unavailable=True)
        return board.edit(task, {}, comment)

    initial = next(state["id"] for state in feed.machines["board"]["states"] if state.get("initial"))
    lane = config.autopilot.eligible_lane(initial)

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

    ranks = _cached(read_ranks, _CHAIN_TTL_S)
    state_dir = base / (config.autopilot.state_dir or "")
    state_dir.mkdir(parents=True, exist_ok=True)
    runtime = build_autopilot(
        config.autopilot,
        state_dir,
        log,
        feed,
        probe,
        start=starter(config.session_start_url, by="autopilot") or builtin_starter(base),
        settle=settle,
        claim=claim,
        chain=lambda: ranks()["chain"],
        p_goals=lambda: ranks()["p_goals"],
        lane=lane,
    )
    runtime.wire_status(publish or feed.publish)
    threading.Thread(target=runtime.sampler.run_forever, args=(stop,), name="autopilot-sampler", daemon=True).start()
    if runtime.loop is not None:
        threading.Thread(target=runtime.loop.run_forever, args=(stop,), name="autopilot-loop", daemon=True).start()
    return runtime
