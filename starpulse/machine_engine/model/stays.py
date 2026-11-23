"""A lane change as the history keeps it."""

__all__ = ["LaneRow"]

#: A lane change as the history keeps it: `(task, at, from, to)`, `at` in epoch seconds.
LaneRow = tuple[str, float, str | None, str]
