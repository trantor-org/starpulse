"""The answers of writes a client may send again, kept by the key the client chose for the send.

A client that times out on a create cannot tell whether the task was filed. It sends the create again with the same
key, and the server answers the first create's answer rather than filing a second task.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

__all__ = ["Replays"]

type _Answer = tuple[int, dict[str, Any]]


class Replays:
    """The successful answer of each write run under a key, the oldest dropped past `kept`. A repeat that arrives
    while the first still runs waits for it; a write that is refused or raises is not kept, so its repeat runs."""

    def __init__(self, kept: int = 512) -> None:
        self._kept = kept
        self._lock = threading.Lock()
        self._runs: OrderedDict[str, Future[_Answer]] = OrderedDict()

    def run(self, key: str | None, work: Callable[[], _Answer]) -> _Answer:
        if key is None:
            return work()
        with self._lock:
            held = self._runs.get(key)
            if held is None:
                held = self._runs[key] = Future()
                owner = True
                while len(self._runs) > self._kept:
                    self._runs.popitem(last=False)
            else:
                owner = False
        if not owner:
            return held.result()
        try:
            answer = work()
        except BaseException as exc:
            self._drop(key, held)
            held.set_exception(exc)
            raise
        if not 200 <= answer[0] < 300:
            self._drop(key, held)
        held.set_result(answer)
        return answer

    def _drop(self, key: str, held: Future[_Answer]) -> None:
        with self._lock:
            if self._runs.get(key) is held:
                del self._runs[key]
