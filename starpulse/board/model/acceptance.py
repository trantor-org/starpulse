"""Which acceptance criteria of a task are still open: neither checked nor struck through (`~~text~~`)."""

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["open_criteria", "resolved"]

_STRIKE = "~~"


def resolved(criterion: Mapping[str, Any]) -> bool:
    """Whether `criterion` is checked or its text is struck through."""
    text = str(criterion["text"]).strip()
    return bool(criterion["checked"]) or (len(text) > 2 * len(_STRIKE) and text.startswith(_STRIKE) and text.endswith(_STRIKE))


def open_criteria(criteria: Iterable[Mapping[str, Any]]) -> list[tuple[int, str]]:
    """Each open criterion as its 1-based number and text, in order."""
    return [(number, str(item["text"])) for number, item in enumerate(criteria, start=1) if not resolved(item)]
