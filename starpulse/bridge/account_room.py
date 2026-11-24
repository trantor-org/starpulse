"""Whether a Claude account has room to start a session: the account-room alert's latest event says."""

from collections.abc import Callable

from starpulse.board.adapters.until_events import follow_until_events
from starpulse.bridge.last_event import last_event_is
from starpulse.bridge.subjects import subject_for
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.wake import StopEvent


def account_room(
    log: EventLog, board: str, alert: str | None, wake: Callable[[], None], stop: StopEvent
) -> Callable[[], bool]:
    """A check that no account lacks room while `alert`'s latest event is `firing`; `wake` runs when it resolves. No
    `alert` named: room is never lacking."""
    if alert is None:
        return lambda: True
    prefix = f"starpulse.{board}.alert.{alert}"
    state: dict[str, bool] = {}

    def seen(subject: str) -> None:
        if subject == f"{prefix}.firing":
            state["firing"] = True
        elif subject == f"{prefix}.resolved":
            state["firing"] = False
            wake()

    follow_until_events(seen, lambda entry: subject_for(board, entry), log, stop)
    state.setdefault("firing", last_event_is(log.engine, f"{prefix}.firing"))
    return lambda: not state["firing"]
