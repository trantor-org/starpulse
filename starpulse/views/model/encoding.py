"""Encoding of the API's bodies: each one validated through its model before it is sent."""

import json
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from hashlib import blake2b
from itertools import batched
from typing import Any

from pydantic import TypeAdapter

from starpulse.board.model.feed.shared import LIVE_WINDOW_S
from starpulse.contracts.api.dto.cue import Pull
from starpulse.contracts.api.dto.flow import Settled
from starpulse.contracts.api.dto.pulls import PullRecord
from starpulse.contracts.api.dto.task import RawTask
from starpulse.contracts.api.registry import BODIES, EVENTS

_ADAPTERS: dict[int, TypeAdapter[Any]] = {}

#: How many rows `encode_stream` dumps into one chunk.
_BATCH = 50


def encode(kind: str, data: Any) -> bytes:
    """The JSON bytes of `data` as the route `kind` may send it, raising `ValidationError` for a body no model of
    `BODIES[kind]` accepts; the page reads only fields a model names."""
    adapter = _adapter(BODIES[kind])  # built once: building one costs more than a small body
    return adapter.dump_json(adapter.validate_python(data), by_alias=True, exclude_unset=True)


def encode_stream(kind: str, data: dict[str, Any], field: str, item: Any, rows: Iterable[Any]) -> Iterator[bytes]:
    """`encode(kind, {**data, field: [...]})` as chunks of `_BATCH` rows each, every row validated as `item` and dumped
    alone, drawn from `rows` only as its chunk is: no more than a batch of rows and their bytes exists at once."""
    adapter = _adapter(item)
    head = encode(kind, {**data, field: []})  # the body with no row, which ends `"field":[]}`
    yield head[:-2]
    for number, batch in enumerate(batched(rows, _BATCH)):
        dumped = b",".join(adapter.dump_json(adapter.validate_python(row), by_alias=True, exclude_unset=True) for row in batch)
        yield dumped if not number else b"," + dumped
    yield b"]}"


def _adapter(annotation: Any) -> TypeAdapter[Any]:
    if (adapter := _ADAPTERS.get(id(annotation))) is None:
        adapter = _ADAPTERS[id(annotation)] = TypeAdapter(annotation)
    return adapter


_Held = dict[Any, tuple[Any, ...]]


def encode_pulls(pulls: list[dict[str, Any]], held: _Held) -> bytes:
    """`encode("pulls", {"pulls": pulls})` with the JSON of each pull request kept in `held` under its repository and
    number: one equal to the record it was dumped from is not validated and dumped again. A record shares its nested
    values with the store, which replaces a record it changes."""
    adapter = _adapter(PullRecord)
    kept: _Held = {}
    dumps = []
    for pull in pulls:
        key = (pull["repo"], pull["number"])
        entry = held.get(key)
        if entry is None or entry[0] != pull:
            entry = (pull, adapter.dump_json(adapter.validate_python(pull), by_alias=True, exclude_unset=True))
        kept[key] = entry
        dumps.append(entry[1])
    held.clear()
    held.update(kept)
    return encode("pulls", {"pulls": []})[:-2] + b",".join(dumps) + b"]}"


def _dump_all(
    items: Iterable[Any], annotation: Any, held: _Held, kept: _Held, project: Callable[[Any], Any]
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
_TASK_DETAIL = ("description", "criteria", "definition_of_done", "moves")
#: What an active task's card keeps: its description, criteria and Definition of Done, which the page shows in the
#: first frame of the task view without a fetch.
_LIVE_DETAIL = ("moves",)
#: The states whose cards keep that detail: the tasks an operator opens. The rest (waiting, done, archived)
#: are most of the board and read `/api/task/<id>` on open.
_ACTIVE_STATES = frozenset({"ready", "in_progress", "review", "needs_attention", "verifying"})


def _move_set_key(moves: dict[str, Any]) -> str:
    """The name of a set of Board-column verdicts: its content's digest, so a task's key never depends on the others."""
    return blake2b(json.dumps(moves, sort_keys=True).encode(), digest_size=6).hexdigest()


def _slim_task(task: dict[str, Any]) -> dict[str, Any]:
    """A Board task without its detail, naming its moves' set in `move_set`; an active task keeps its description
    and criteria."""
    left_out = _LIVE_DETAIL if task.get("state") in _ACTIVE_STATES else _TASK_DETAIL
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
    """The tasks created or settled in the 24 hours before the snapshot, the window the writer holds: the page draws
    the day's arrivals from them, and a page's local midnight is never further back."""
    since = data["now"] - LIVE_WINDOW_S
    return {
        task_id: entry
        for task_id, entry in data["settled"].items()
        if (entry["created"] or 0) >= since or (entry["at"] or 0) >= since
    }


def _milestone_done(data: dict[str, Any]) -> dict[str, int]:
    """Each milestone's completed count: its settled Tasks plus the Done ones a read-model feed counted off the board."""
    settled = Counter(e["milestone"] for e in data["settled"].values() if e["milestone"] and e["state"] == "completed")
    return dict(settled + Counter(data.get("milestone_done", {})))


def _trail_points(agent: dict[str, Any], names: dict[str, int]) -> dict[str, Any]:
    """`agent` with its trail as `[state, event, dt]` points indexing `names`, which takes each name it meets: `dt` is the
    milliseconds since the step before it, the epoch for the first, so a step's time is the same whichever steps the
    trail's cap left before it. A step's `id` follows as a fourth member; its `data` is not sent."""
    before = 0
    points = []
    for step in agent.get("trail") or ():
        at = round(step["at"] * 1000)
        point = [names.setdefault(step["state"], len(names)), names.setdefault(step["event"], len(names)), at - before]
        points.append(point + [step["id"]] if step.get("id") is not None else point)
        before = at
    return {**agent, "trail": points} if points else agent


def _interned(agents: Iterable[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    """The state and event names of the `agents`' trails, each once, and the agents with each trail drawn by `_trail_points`."""
    names: dict[str, int] = {}
    drawn = [_trail_points(agent, names) for agent in agents]
    return list(names), drawn


def _dump_machine_flow(flow: dict[str, Any], held: _Held, kept: _Held) -> tuple[list[str], list[bytes]]:
    """The flow's trail names and the JSON of each of its agents as `_trail_points` and `RawTask` draw them. A flow keeps
    its names in `held` and only adds to them, so an agent's JSON stays while its object does: the feed replaces an
    agent it moves, and a move dumps that one agent. A name no agent uses any more stays listed until the writer restarts."""
    adapter = _adapter(RawTask)
    names: dict[str, int] = (held.get(("names", flow["name"])) or ({},))[0]
    kept[("names", flow["name"])] = (names,)
    dumps = []
    for agent in flow["agents"]:
        entry = held.get(("machine", id(agent)))
        if entry is None or entry[0] is not agent or entry[1] is not names:
            dump = adapter.dump_json(adapter.validate_python(_trail_points(agent, names)), by_alias=True, exclude_unset=True)
            entry = (agent, names, dump)
        kept[("machine", id(agent))] = entry
        dumps.append(entry[2])
    return list(names), dumps


def _drawn_flow(flow: dict[str, Any]) -> dict[str, Any]:
    names, agents = _interned(flow["agents"])
    return {**flow, "names": names, "agents": agents} if names else flow


def _drawn_pulls(pulls: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Each task's pull requests with only the fields `Pull` declares: a record also keeps what the feed reads itself,
    such as `files` and `applied_by`, which the page is not sent."""
    return {
        task: [{k: v for k, v in pull.items() if k in Pull.model_fields} for pull in found]
        for task, found in pulls.items()
    }


def slim_snapshot(data: Any) -> Any:
    """`data` as the page is sent it: each Board task without its description, criteria and moves (it reads them
    from `/api/task/<id>` on open, and the moves through the `move_sets` table; an active task keeps its
    description and criteria), only the recent settled tasks, and
    each milestone's completed count; `/api/events` draws its `snapshot` frames with it too. A verb or the held-tasks
    stream reads the whole of `data`, never this."""
    flows = data["flows"]
    board = flows[0] if flows and flows[0]["name"] == "board" else None
    drawn = {**data, "milestone_done": _milestone_done(data), "settled": _recent_settled(data)}
    drawn.pop("cold_done", None)
    if data.get("pulls"):
        drawn["pulls"] = _drawn_pulls(data["pulls"])
    if board:
        drawn["move_sets"] = _move_sets(board["agents"])
        flows = [{**board, "agents": [_slim_task(task) for task in board["agents"]]}, *flows[1:]]
    drawn["flows"] = [flows[0], *map(_drawn_flow, flows[1:])] if board else list(map(_drawn_flow, flows))
    return drawn


def encode_snapshot(data: Any, held: _Held) -> bytes:
    """`encode("snapshot", slim_snapshot(data))`, the one body the API serves, with the JSON of each board task and
    machine agent kept in `held` between calls.

    `held` maps `id(object)` to the object and its JSON (an agent under `("machine", id)`, a flow's trail names under
    `("names", flow)`): the feed replaces a task, agent or settled entry it changes rather than editing it, so one met
    again encodes the same, and one no longer listed is forgotten. Those are most of the snapshot (the settled day's
    entries alone 3.8 of its 4.9 MB), so a build after one change validates and dumps only what changed and the rest of
    the document.
    """
    flows = data["flows"]
    if not flows or flows[0]["name"] != "board":
        return encode("snapshot", slim_snapshot(data))
    kept: _Held = {}
    tasks = _dump_all(flows[0]["agents"], RawTask, held, kept, _slim_task)
    machines = [_dump_machine_flow(flow, held, kept) for flow in flows[1:]]
    bare = [
        {**flow, "agents": [], **({"names": names} if names else {})}
        for flow, (names, _) in zip(flows[1:], machines, strict=True)
    ]
    drawn = {
        **slim_snapshot({**data, "flows": [{**flows[0], "agents": []}, *bare]}),
        "move_sets": _move_sets(flows[0]["agents"]),
    }
    recent, drawn["settled"] = drawn["settled"], {}
    settled = _dump_settled(recent, held, kept)
    held.clear()
    held.update(kept)
    body = encode("snapshot", drawn)
    try:
        body = _splice_flows(body, [tasks, *(dumps for _, dumps in machines)], [flow["name"] for flow in flows])
        return _splice_settled(body, settled)
    except ValueError:  # the document is not drawn as it was: encode it whole
        return encode("snapshot", slim_snapshot(data))


def _splice_flows(body: bytes, agents: list[list[bytes]], names: list[str]) -> bytes:
    """`body` with each flow's empty `"agents":[]` replaced by its drawn agents, the flows taken in order; ValueError when
    one is absent."""
    parts, cursor, search = [], 0, body.index(b'"flows":[')
    for drawn, name in zip(agents, names, strict=True):
        at = body.index(b'"agents":[]', body.index(b'{"name":%s' % json.dumps(name, ensure_ascii=False).encode(), search))
        parts += [body[cursor:at], b'"agents":[%s]' % b",".join(drawn)]
        cursor = search = at + len(b'"agents":[]')
    return b"".join(parts) + body[cursor:]


def _dump_settled(recent: dict[str, dict[str, Any]], held: _Held, kept: _Held) -> bytes:
    """The `"id":entry` pairs of the `recent` settled tasks, each kept in `held` under `("settled", id)` while the feed
    holds the same entry object: it replaces an entry it changes."""
    adapter = _adapter(Settled)
    pairs = []
    for task_id, entry in recent.items():
        pair = held.get(("settled", task_id))
        if pair is None or pair[0] is not entry:
            dump = adapter.dump_json(adapter.validate_python(entry), by_alias=True, exclude_unset=True)
            pair = (entry, json.dumps(task_id, ensure_ascii=False).encode() + b":" + dump)
        kept[("settled", task_id)] = pair
        pairs.append(pair[1])
    return b",".join(pairs)


def _splice_settled(body: bytes, pairs: bytes) -> bytes:
    """`body` with its empty `"settled":{}` replaced by `pairs`; ValueError unless there is exactly one to replace."""
    if body.count(b'"settled":{}') != 1:
        raise ValueError("settled")
    return body.replace(b'"settled":{}', b'"settled":{%s}' % pairs)


def event(name: str, data: Any) -> str:
    """The JSON text of the `data` of `/api/events`' event `name`, raising `ValidationError` for one its model refuses."""
    model = EVENTS[name]
    if name == "snapshot":  # a rebuilt snapshot the writer stores as a delta is drawn as the served body is
        data = slim_snapshot(data)
    elif name == "pulls" and data.get("pulls"):
        data = {**data, "pulls": _drawn_pulls(data["pulls"])}
    if name == "move":
        names, (agent,) = _interned([data["agent"]])
        data = {**data, "agent": agent, **({"names": names} if names else {})}
    return model.model_validate(data).model_dump_json(by_alias=True, exclude_unset=True)
