"""Push level and forwarding status on the feed so the page need not poll those GET routes."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.hub.forward import Forwarder

logger = logging.getLogger(__name__)

BuildLevel = Callable[[], dict[str, Any] | None]


class _Debounced:
    """Call `fn` once `delay_s` after the last nudge; a zero delay runs `fn` on the calling thread."""

    def __init__(self, fn: Callable[[], None], delay_s: float) -> None:
        self._fn = fn
        self._delay_s = delay_s
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def __call__(self) -> None:
        if self._delay_s <= 0:
            self._fn()
            return
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay_s, self._fn)
            self._timer.daemon = True
            self._timer.start()


def wire_level(feed: BoardFeed, build: BuildLevel, *, delay_s: float = 0.25) -> None:
    """Publish a `level` feed event after board task changes, built by `build` (None skips the publish)."""

    def push() -> None:
        try:
            body = build()
        except Exception:  # the page keeps its last level; the next lane change tries again
            logger.exception("StarPulse: cannot build a level event")
            return
        if body is not None:
            feed.publish("level", body)

    nudge = _Debounced(push, delay_s)
    original = feed._publish

    def published(kind: str, data: dict) -> None:
        original(kind, data)
        if kind == "task":
            nudge()

    feed._publish = published  # type: ignore[method-assign]


def wire_forwarding(feed: BoardFeed, forwarder: Forwarder) -> Callable[[], None]:
    """Publish a `forwarding` feed event after each opt-in change; returns the push, which the forwarding worker's
    reports (`forward_report.Reported`) call when the forwarder's runtime changed."""

    def push() -> None:
        try:
            feed.publish("forwarding", {"configured": True, **forwarder.status()})
        except Exception:
            logger.exception("StarPulse: cannot build a forwarding event")

    original_set = forwarder.opt_in.set

    def set_opt(value: bool) -> None:
        original_set(value)
        forwarder.forget_status()
        push()

    forwarder.opt_in.set = set_opt  # type: ignore[method-assign]
    return push
