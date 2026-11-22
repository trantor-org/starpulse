"""Which acceptance criteria of a task are still open: neither checked nor struck through (`~~text~~`)."""

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["open_criteria", "resolved"]

_STRIKE = "~~"


def resolved(criterion: Mapping[str, Any]) -> bool:
    """Whether `criterion` is checked or its text is struck through."""
    text = str(criterion["text"]).strip()
    head, _, note = text.removeprefix(_STRIKE).partition(_STRIKE)
    struck = text.startswith(_STRIKE) and bool(head.strip()) and _STRIKE in text[2:] and _STRIKE not in note
    return bool(criterion["checked"]) or struck


def open_criteria(criteria: Iterable[Mapping[str, Any]]) -> list[tuple[int, str]]:
    """Each open criterion as its 1-based number and text, in order."""
    return [(number, str(item["text"])) for number, item in enumerate(criteria, start=1) if not resolved(item)]
