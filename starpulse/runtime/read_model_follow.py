"""Keep the Task read model folded and tell the page of each Task that changed."""

from __future__ import annotations

import logging
import threading
from typing import Protocol

__all__ = ["follow"]

logger = logging.getLogger(__name__)


class _Projector(Protocol):
    def catch_up(self) -> int: ...


class _Feed(Protocol):
    def follow_read_model(self) -> int: ...


def follow(
    projector: _Projector | None, feed: _Feed, stop: threading.Event, interval_s: float = 0.5
) -> threading.Thread:
    """Run `projector.catch_up` (none: another process folds) and then `feed.follow_read_model` every `interval_s` until `stop`; a pass that raises
    is logged and the next one runs."""

    def run() -> None:
        while not stop.is_set():
            try:
                if projector is not None:
                    projector.catch_up()
                feed.follow_read_model()
            except Exception:
                logger.exception("StarPulse: the read model pass failed")
            stop.wait(interval_s)

    thread = threading.Thread(target=run, name="read-model-follow", daemon=True)
    thread.start()
    return thread
