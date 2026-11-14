"""The events that re-evaluate a Start Criterion: a run that ends or a pull request that merges."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from starpulse.board.model.criteria import Evaluator
from starpulse.event_log.events import STREAM as MACHINE_STREAM
from starpulse.event_log.wake import StopEvent

if TYPE_CHECKING:
    from starpulse.event_log.event_log import Entry, EventLog

#: The runs adapter's stream (`runs.run_events.STREAM`), named here because the Board imports no other context.
RUNS_STREAM = "runs:events"
ENDED = frozenset({"succeeded", "failed", "aborted", "skipped"})
PULL_REQUEST_MACHINE = "github-pull-request"


def criteria_topic(entry: Entry) -> str | None:
    """The topic a criterion's `refresh.on` names that `entry` announces: `run:<dag>` for a run that ended, `merge` for a
    merged pull request, else None."""
    fields = entry.fields
    if entry.stream == RUNS_STREAM:
        ended = "step" not in fields and fields.get("status") in ENDED
        return f"run:{fields.get('workflow')}" if ended else None
    merged = fields.get("machine") == PULL_REQUEST_MACHINE and fields.get("event") == "PR_MERGED"
    return "merge" if entry.stream == MACHINE_STREAM and merged else None


def follow_criteria_events(
    wake: Callable[[], None],
    evaluate: Callable[[str, str], list[dict]] | None,
    log: EventLog,
    stop: StopEvent,
) -> threading.Thread | None:
    """Evaluate the Start Criteria again within seconds of the event they await, so they poll only as a net. Each run
    that ends or pull request that merges after this call invalidates the results that name it and calls `wake`, the
    criteria pass to run. None when `evaluate` keeps no hints to invalidate."""
    if not isinstance(evaluate, Evaluator):
        return None
    from starpulse.event_log.event_log import Tail  # the server imports no database stack until a store opens

    def handle(entry: Entry) -> None:
        if (topic := criteria_topic(entry)) and evaluate.invalidate(topic):
            wake()

    tail = Tail.live(log, RUNS_STREAM, streams=[RUNS_STREAM, MACHINE_STREAM])
    thread = threading.Thread(target=tail.run, args=(handle, stop), name="board-criteria-events", daemon=True)
    thread.start()
    return thread
