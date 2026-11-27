"""The lane record of a board write, made in the transaction that appends the write's move to its Task's History.

A feed sets the recorder around a write with `recording`; the History append that moves a task asks `recorder()` for
the record of that move before it opens its transaction and runs it inside, so the move and its lane row land together
or neither does. Outside `recording`, a write records no lane here, and the feed records it after the write.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

#: The record of one move into the History append's open connection; True when it wrote a lane row.
MoveRecord = Callable[[Any], bool]
#: The record of `task`'s move to `lane` at `at`, prepared before the transaction opens.
MoveRecorder = Callable[[str, str, float], MoveRecord]

_RECORDER: ContextVar[MoveRecorder | None] = ContextVar("lane_recorder", default=None)


@contextmanager
def recording(recorder: MoveRecorder) -> Iterator[None]:
    """Record each move the writes inside append to a History through `recorder`, in the append's transaction."""
    token = _RECORDER.set(recorder)
    try:
        yield
    finally:
        _RECORDER.reset(token)


def recorder() -> MoveRecorder | None:
    """The recorder of the write running in this context, or None outside `recording`."""
    return _RECORDER.get()
