"""How often each log follower woke and how many of those wakes moved no events head, for `/metrics`:
`starpulse_follower_wakes_total{child,follower,head_moved}`.

The event log counts the wakes (`EventLog.wakes`) and keeps their text in its state under `STATE` plus the child's
name every `event_log.PUBLISH_EVERY` wakes (never on a timer), for the Page API to relay. A follower on a quiet wake
did a pass that read nothing new."""

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING

from starpulse.event_log.kept_text import kept_text

if TYPE_CHECKING:  # annotation only: the event log imports this module
    from starpulse.event_log.event_log import EventLog

NAME = "starpulse_follower_wakes_total"
STATE = "follower.wakes."


def samples(counts: Mapping[tuple[str, bool], int], child: str) -> str:
    """The counter's sample lines for `child`'s wake `counts`, by follower and whether the head moved."""
    return "".join(
        f'{NAME}{{child="{child}",follower="{follower}",head_moved="{str(moved).lower()}"}} {n}\n'
        for (follower, moved), n in sorted(counts.items())
    )


def metrics_of(log: EventLog, children: Sequence[str]) -> Callable[[], str]:
    """The wake counts each of `children` kept, as one counter family; empty while none kept any."""
    kept = [kept_text(log, STATE + child) for child in children]

    def read() -> str:
        text = "".join(read() for read in kept)
        return f"# HELP {NAME} Wakes of a log follower thread\n# TYPE {NAME} counter\n{text}" if text else ""

    return read
