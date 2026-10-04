"""A stream consumer that notices when the stream was trimmed past entries it never read."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import redis.exceptions

from starpulse.board_feed import stream_id
from starpulse.streams import StreamConsumer


def _after(entry_id: str) -> str:
    millis, _, sequence = entry_id.partition("-")  # pragma: no mutate: an id holds one "-"
    return f"{millis}-{int(sequence) + 1}"


class GapWatchingConsumer(StreamConsumer):
    """Before each read, report entries the stream dropped that the group never delivered.

    A trim removes the oldest entries first, so the group has lost some when the oldest entry the stream still
    holds is past the group's last-delivered id and the stream has added more entries than the group has read plus
    the stream still holds. `on_gap(after_id, before_id, lost)` then names the loss: `lost` entries with ids after
    `after_id` and before `before_id`, the oldest entry still held (the one after the newest, when none is).
    The same loss reported again, because the group has read nothing since, repeats `after_id`, so `on_gap` must
    treat a repeated `after_id` as one gap.

    Redis re-estimates the group's read count once it delivers past a trim, so the check runs before every
    read. A trim that outruns the consumer inside one poll is lost to the next check; a consumer keeping up
    never loses entries this way. A group that has not yet read (or whose count Redis cannot know, after an
    `XDEL`) reports nothing.
    """

    def __init__(self, *, on_gap: Callable[[str, str, int], None], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.on_gap = on_gap

    def consume_once(self, client: Any) -> None:
        self._report_gap(client)
        super().consume_once(client)

    def _report_gap(self, client: Any) -> None:
        try:
            groups = client.xinfo_groups(self.stream)
            info = client.xinfo_stream(self.stream)
        except redis.exceptions.ResponseError:  # no stream yet, so nothing was trimmed from it
            return
        group = next((g for g in groups if g["name"] == self.group), None)
        if group is None or group["entries-read"] is None:
            return
        first = info["first-entry"]
        before = first[0] if first else _after(info["last-generated-id"])
        lost = info["entries-added"] - group["entries-read"] - info["length"]
        if lost <= 0:
            return
        if stream_id(before) > stream_id(
            group["last-delivered-id"]
        ):  # pragma: no mutate: a trim past the group's entry leaves it gone, so equal means no loss
            self.on_gap(group["last-delivered-id"], before, lost)
