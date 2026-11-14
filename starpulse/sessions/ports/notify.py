"""The notify capability of a harness adapter: tell a running or ended session about events on its subscribed subjects.

A `Registration` is what the harness gave the session to be reached by: its inbox socket and token, and the directory
it works in. An adapter's `notify` hands it the events of one delivery, oldest first, and says whether they reached the
session; an event that did not is delivered again.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Line:
    """One event as one line of text, on the subject it was published to."""

    subject: str
    text: str


@dataclass(frozen=True)
class Registration:
    session: str
    socket: str
    token: str
    cwd: str


class Notifier(Protocol):
    def notify(self, registration: Registration, lines: Sequence[Line]) -> bool: ...
