"""The inbox port: where a verified delivery is made durable before the listener answers."""

from __future__ import annotations

from collections.abc import Collection
from typing import Protocol

from starpulse.github.model.delivery import Delivery

__all__ = ["Inbox", "InboxError"]


class InboxError(Exception):
    """The delivery could not be made durable; the listener answers 503 so GitHub keeps it as failed."""


class Inbox(Protocol):
    def save(self, delivery: Delivery, source: str = "webhook") -> bool:
        """Commit `delivery` once, recorded as from `source`: `True` when it is a new row, `False` when its `delivery_id`
        was already saved.

        Raises `InboxError` when the commit fails, with no row written."""
        ...

    def known(self, delivery_ids: Collection[str]) -> set[str]:
        """The `delivery_ids` that already have a row."""
        ...
