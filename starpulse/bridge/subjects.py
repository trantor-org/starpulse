"""Which JetStream subject, if any, a log entry is published on: `starpulse.<board>.<entity>.<id>.<event>`.

A lane move of the board (`board:lanes`) is `task.<task>.moved`. A machine event (`machine:events`) is
`pr.<number>.<event>` when it names a pull request, else `task.<task>.<event>`; a machine event of a run alone, and every
other stream, has no subject. The pull request number comes from the event's `data.pr`, else from the `/pull/<n>` the
`ci` machine puts in its event id. `<event>` is the event lowercased without a leading `PR_`, so the `github-pull-request`
machine's `PR_MERGED` and the `ci` machine's `MERGED` are both `merged`. The `pr-checks` machine is the exception: its
`CHECK_REPORTED` is `pr.<number>.check.<data.name>` and its `ROLLUP_<STATE>` is `pr.<number>.checks.<state>`.
The `alert` machine's `FIRING` and `RESOLVED`, keyed by the rule as their run, are `alert.<rule>.firing` and `.resolved`.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starpulse.event_log.event_log import Entry

LANES = "board:lanes"
MACHINE = "machine:events"
STREAMS = (LANES, MACHINE)

_PULL = re.compile(r"/pull/(\d+)")
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def token(value: object) -> str:
    """`value` as one subject token: a run of characters NATS reads as structure (`.`, `*`, `>`, space) becomes `_`."""
    return _UNSAFE.sub("_", str(value)).strip("_")


def pull_number(entry: Entry) -> str | None:
    pr = (entry.fields.get("data") or {}).get("pr")
    if pr:
        return token(pr)
    found = _PULL.search(entry.event_id)
    return found.group(1) if found else None


def subject_for(board: str, entry: Entry) -> str | None:
    """The subject of `entry` on `board`, or None when the bridge does not publish it."""
    fields = entry.fields
    if entry.stream == LANES:
        task = token(fields.get("task") or "")
        return f"starpulse.{board}.task.{task}.moved" if task else None
    if entry.stream != MACHINE:
        return None
    event = token(str(fields.get("event") or "").removeprefix("PR_").lower())
    if not event:
        return None
    number = pull_number(entry)
    if fields.get("machine") == "alert":
        rule = token(fields.get("run") or "")
        return f"starpulse.{board}.alert.{rule}.{event}" if rule else None
    if fields.get("machine") == "pr-checks":
        named = token((fields.get("data") or {}).get("name") or "")
        if not number:
            return None
        if event == "check_reported":
            return f"starpulse.{board}.pr.{number}.check.{named}" if named else None
        return f"starpulse.{board}.pr.{number}.checks.{event.removeprefix('rollup_')}"
    if number:
        return f"starpulse.{board}.pr.{number}.{event}"
    task = token(fields.get("task") or "")
    return f"starpulse.{board}.task.{task}.{event}" if task else None


def payload(entry: Entry) -> bytes:
    """The message body: the entry as the log holds it, so a subscriber dedupes on `event_id`."""
    body = {"event_id": entry.event_id, "stream": entry.stream, "at": entry.at, "fields": entry.fields}
    return json.dumps(body, separators=(",", ":")).encode()
