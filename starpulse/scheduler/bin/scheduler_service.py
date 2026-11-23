"""The scheduler's runtime started over a board: the sampler and the dispatch loop, on daemon threads.

`starpulse worker scheduler` starts it as its own process (`starpulse.scheduler.bin.scheduler_worker`), a child `serve` supervises. It is not
imported at the top of `starpulse.runtime.server`, so the Delivery worker's import closure holds no scheduler module.
"""

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.seam import Board, Written
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.claude_sessions import DEFAULT_TRANSCRIPTS, transcript_written
from starpulse.event_log.wake import StopEvent
from starpulse.scheduler.adapters.pressure import watch
from starpulse.scheduler.adapters.runtime import Runtime
from starpulse.scheduler.adapters.runtime import build as build_scheduler
from starpulse.scheduler.adapters.starter import builtin_starter
from starpulse.scheduler.bin.blocks import SchedulerConfig


def start_scheduler(
    config: SchedulerConfig,
    base: Path,
    feed: BoardFeed,
    board: Board,
    log: EventLog,
    stop: StopEvent,
    probe: Callable[[], Mapping[str, float]] | None = None,
    publish: Callable[[str, dict[str, Any]], None] | None = None,
    *,
    starter: Callable[..., Any],
    delivered: Callable[[EventLog, Mapping[str, Any]], bool],
    ender: Callable[[Sequence[str]], Callable[[str], None] | None],
    clock: Callable[[], float] = time.time,
) -> Runtime:
    """The scheduler's runtime with its sampler and dispatch loop running on daemon threads until `stop` is set.

    The loop admits from the lane `[scheduler] lane` names (else the board's initial lane), starts a session through
    `session_start_url` (else the built-in tmux starter in `base`). `runtime` passes `starter`, `delivered` and `ender`, as no context imports them.
    """

    def claim(task: str, comment: str) -> Written:
        return board.edit(task, {}, comment)

    def merged(agent: Mapping[str, Any]) -> bool:
        return delivered(log, agent)

    initial = next(state["id"] for state in feed.machines["board"]["states"] if state.get("initial"))
    lane = config.scheduler.eligible_lane(initial)

    runtime = build_scheduler(
        config.scheduler,
        log,
        feed,
        probe,
        start=starter(config.session_start_url, by="scheduler") or builtin_starter(base),
        claim=claim,
        merged=merged,
        lane=lane,
        clock=clock,
        transcript=transcript_written(Path(DEFAULT_TRANSCRIPTS).expanduser()),
        end=ender(config.bridge.end) or (lambda task: None),
    )
    runtime.wire_status(publish or feed.publish)
    pressure = threading.Event()
    watch(stop, pressure)
    threading.Thread(
        target=runtime.sampler.run_forever, args=(stop, pressure), name="scheduler-sampler", daemon=True
    ).start()
    if runtime.loop is not None:
        threading.Thread(target=runtime.loop.run_forever, args=(stop,), name="scheduler-loop", daemon=True).start()
    return runtime
