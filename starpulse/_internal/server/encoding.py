"""Encoding of the API's bodies: each one validated through its model before it is sent."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from hashlib import blake2b
from typing import Any

from pydantic import TypeAdapter

from starpulse.contracts.api.dto.cue import Pull
from starpulse.contracts.api.dto.task import RawTask
from starpulse.contracts.api.registry import BODIES, EVENTS

_ADAPTERS: dict[int, TypeAdapter[Any]] = {}


def encode(kind: str, data: Any) -> bytes:
    """The JSON bytes of `data` as the route `kind` may send it, raising `ValidationError` for a body no model of
    `BODIES[kind]` accepts; the page reads only fields a model names."""
    adapter = _adapter(BODIES[kind])  # built once: building one costs more than a small body
    return adapter.dump_json(adapter.validate_python(data), by_alias=True, exclude_unset=True)


def _adapter(annotation: Any) -> TypeAdapter[Any]:
    if (adapter := _ADAPTERS.get(id(annotation))) is None:
        adapter = _ADAPTERS[id(annotation)] = TypeAdapter(annotation)
    return adapter


_Held = dict[int, tuple[Any, bytes]]


def _dump_all(
    items: Iterable[Any], annotation: Any, held: _Held, kept: _Held, project: Callable[[Any], Any] = lambda item: item
) -> list[bytes]:
    """The JSON of each of `items` as `project` draws it: the one `held` has for the object, else made now. Each is
    recorded in `kept`."""
    adapter = _adapter(annotation)
    dumps = []
    for item in items:
        kept[id(item)] = entry = held.get(id(item)) or (
            item,
            adapter.dump_json(adapter.validate_python(project(item)), by_alias=True, exclude_unset=True),
        )
        dumps.append(entry[1])
    return dumps


#: The fields of a Board task the page reads from `/api/task/<id>` when it opens one, so a snapshot leaves them out.
_TASK_DETAIL = ("description", "criteria", "moves")
#: What an In Progress task's card keeps: its live description and criteria, which the page shows without a fetch.
_LIVE_DETAIL = ("moves",)


def _move_set_key(moves: dict[str, Any]) -> str:
    """The name of a set of Board-column verdicts: its content's digest, so a task's key never depends on the others."""
    return blake2b(json.dumps(moves, sort_keys=True).encode(), digest_size=6).hexdigest()


def _slim_task(task: dict[str, Any]) -> dict[str, Any]:
    """A Board task without its detail, naming its moves' set in `move_set`; an In Progress task keeps its description
    and criteria."""
    left_out = _LIVE_DETAIL if task.get("state") == "in_progress" else _TASK_DETAIL
    slim = {key: value for key, value in task.items() if key not in left_out}
    if task.get("moves"):
        slim["move_set"] = _move_set_key(task["moves"])
    return slim


def _move_sets(tasks: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    sets = {}
    for task in tasks:
        if moves := task.get("moves"):
            sets[_move_set_key(moves)] = moves
    return sets


def _recent_settled(data: dict[str, Any]) -> dict[str, Any]:
    """The tasks created or settled since the start of the day before the snapshot's local day: the page draws the
    day's arrivals from them, and the extra day covers a page whose midnight falls earlier than the server's."""
    since = (
        datetime.fromtimestamp(data["now"]).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    ).timestamp()
    return {
        task_id: entry
        for task_id, entry in data["settled"].items()
        if (entry["created"] or 0) >= since or (entry["at"] or 0) >= since
    }


def _milestone_done(settled: dict[str, Any]) -> dict[str, int]:
    return dict(Counter(e["milestone"] for e in settled.values() if e["milestone"] and e["state"] == "completed"))


def _drawn_pulls(pulls: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Each task's pull requests with only the fields `Pull` declares: a record also keeps what the feed reads itself,
    such as `files` and `applied_by`, which the page is not sent."""
    return {
        task: [{k: v for k, v in pull.items() if k in Pull.model_fields} for pull in found]
        for task, found in pulls.items()
    }


def full_snapshot(data: Any) -> Any:
    """`data` as `?view=full` sends it: whole, but with each pull request drawn as the page is sent it."""
    return {**data, "pulls": _drawn_pulls(data["pulls"])} if data.get("pulls") else data


def slim_snapshot(data: Any) -> Any:
    """`data` as the page is sent it: each Board task without its description, criteria and moves (it reads them
    from `/api/task/<id>` on open, and the moves through the `move_sets` table; an In Progress task keeps its
    description and criteria), only the recent settled tasks, and
    each milestone's completed count. A verb or a held stream reads the whole of `data`, never this."""
    flows = data["flows"]
    board = flows[0] if flows and flows[0]["name"] == "board" else None
    drawn = {**data, "milestone_done": _milestone_done(data["settled"]), "settled": _recent_settled(data)}
    drawn.pop("cold_done", None)
    if data.get("pulls"):
        drawn["pulls"] = _drawn_pulls(data["pulls"])
    if board:
        drawn["move_sets"] = _move_sets(board["agents"])
        drawn["flows"] = [{**board, "agents": [_slim_task(task) for task in board["agents"]]}, *flows[1:]]
    return drawn


def encode_snapshot(data: Any, held: _Held) -> bytes:
    """`encode("snapshot", data)`, with the JSON of each board task kept in `held` between calls.

    `held` maps `id(object)` to the object and its JSON: the feed replaces a task it changes rather than
    editing it, so one met again encodes the same, and one no longer listed is forgotten. Those are most of the
    snapshot, so a build after one change validates and dumps only what changed and the rest of the document.
    """
    flows = data["flows"]
    if not flows or flows[0]["name"] != "board":
        return encode("snapshot", slim_snapshot(data))
    kept: _Held = {}
    tasks = _dump_all(flows[0]["agents"], RawTask, held, kept, _slim_task)
    held.clear()
    held.update(kept)
    drawn = {
        **slim_snapshot({**data, "flows": [{**flows[0], "agents": []}, *flows[1:]]}),
        "move_sets": _move_sets(flows[0]["agents"]),
    }
    body = encode("snapshot", drawn)
    try:
        return _splice(body, b'"agents":[]', b'"agents":[%s]' % b",".join(tasks), after=b'"flows":[{"name":"board"')
    except ValueError:  # the document is not drawn as it was: encode it whole
        return encode("snapshot", slim_snapshot(data))


def _splice(body: bytes, marker: bytes, drawn: bytes, after: bytes = b"") -> bytes:
    """`body` with the first `marker` past the first `after` replaced by `drawn`; ValueError when either is absent."""
    at = body.index(marker, body.index(after))
    return body[:at] + drawn + body[at + len(marker) :]


def event(name: str, data: Any) -> str:
    """The JSON text of the `data` of `/api/events`' event `name`, raising `ValidationError` for one its model refuses."""
    model = EVENTS[name]
    if name in ("pulls", "snapshot") and data.get("pulls"):
        data = {**data, "pulls": _drawn_pulls(data["pulls"])}
    return model.model_validate(data).model_dump_json(by_alias=True, exclude_unset=True)
