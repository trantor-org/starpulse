"""Encoding of the API's bodies: each one validated through its model before it is sent."""

import json
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from itertools import batched
from operator import is_
from typing import Any, NamedTuple

from pydantic import TypeAdapter

from starpulse.board.model.feed.shared import LIVE_WINDOW_S
from starpulse.contracts.api.dto.cue import Pull
from starpulse.contracts.api.dto.flow import Settled
from starpulse.contracts.api.dto.task import RawTask
from starpulse.contracts.api.registry import BODIES
from starpulse.machine_engine.model.transitions import done_lanes

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
#: What an active task's card keeps: its moves, which `starpulse task moves` reads from the snapshot.
_LIVE_DETAIL: tuple[str, ...] = ()
#: The states whose cards keep that detail: the tasks an operator opens. The rest (waiting, done, archived)
#: are most of the board and read `/api/task/<id>` on open.
_ACTIVE_STATES = frozenset({"ready", "in_progress", "review", "needs_attention", "verifying"})


def _slim_task(task: dict[str, Any]) -> dict[str, Any]:
    """A Board task without its detail; an active task keeps its description and criteria."""
    left_out = _LIVE_DETAIL if task.get("state") in _ACTIVE_STATES else _TASK_DETAIL
    return {key: value for key, value in task.items() if key not in left_out}


def recent_settled(data: dict[str, Any]) -> dict[str, Any]:
    """The tasks created or settled in the 24 hours before the snapshot, the window the writer holds: the page draws
    the day's arrivals from them, and a page's local midnight is never further back."""
    since = data["now"] - LIVE_WINDOW_S
    return {
        task_id: entry
        for task_id, entry in data["settled"].items()
        if (entry["created"] or 0) >= since or (entry["at"] or 0) >= since
    }


def settled_counts(data: dict[str, Any]) -> Counter:
    """How many of the settled tasks each milestone has completed."""
    done = done_lanes(data["roles"]["done"])
    return Counter(e["milestone"] for e in data["settled"].values() if e["milestone"] and e["state"] in done)


def milestone_done(data: dict[str, Any], counted: Counter | None = None) -> dict[str, int]:
    """Each milestone's completed count: its settled Tasks (`counted`, when the caller holds them) plus the Done ones a
    read-model feed counted off the board."""
    return dict((settled_counts(data) if counted is None else counted) + Counter(data.get("milestone_done", {})))


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
    agents = flow["agents"]
    last = held.get(("flow", flow["name"]))
    if last is not None and last[0] == agents and last[1] is names:  # the same agents, which the list compare finds by identity
        kept.update(last[3])
        kept[("flow", flow["name"])] = last
        return list(names), last[2]
    dumps = []
    own: _Held = {}
    for agent in agents:
        entry = held.get(("machine", id(agent)))
        if entry is None or entry[0] is not agent or entry[1] is not names:
            dump = adapter.dump_json(adapter.validate_python(_trail_points(agent, names)), by_alias=True, exclude_unset=True)
            entry = (agent, names, dump)
        own[("machine", id(agent))] = entry
        dumps.append(entry[2])
    kept.update(own)
    kept[("flow", flow["name"])] = list(agents), names, dumps, own
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
    """`data` as `/api/snapshot` sends it: each Board task without its description, criteria and moves (an active task
    keeps its moves), only the recent settled tasks, and each milestone's completed count. A verb
    reads the whole of `data`, never this."""
    flows = data["flows"]
    board = flows[0] if flows and flows[0]["name"] == "board" else None
    drawn = {**data, "milestone_done": milestone_done(data), "settled": recent_settled(data)}
    drawn.pop("cold_done", None)
    if data.get("pulls"):
        drawn["pulls"] = _drawn_pulls(data["pulls"])
    if board:
        flows = [{**board, "agents": [_slim_task(task) for task in board["agents"]]}, *flows[1:]]
    drawn["flows"] = [flows[0], *map(_drawn_flow, flows[1:])] if board else list(map(_drawn_flow, flows))
    return drawn


#: The snapshot fields `encode_snapshot` keeps the JSON of between builds, each with the emptiest value its model
#: accepts, which stands in until the JSON is spliced in.
_PARTS: dict[str, Any] = {"dags": []}


class _Day(NamedTuple):
    """The settled tasks of the last 24 hours as `encode_snapshot` last drew them, and what they were drawn from."""

    settled: dict[str, Any]  # the feed's settled tasks, copied
    done: Any  # the lanes that count as done
    since: float  # the clock it was drawn at
    until: float  # the clock after which a task leaves the day
    pairs: dict[str, tuple[Any, bytes]]  # each task's entry and its `"id":entry` JSON
    counted: Counter  # the completed count of each milestone over every settled task
    dumped: bytes  # `pairs` joined


def _same(held: dict[str, Any], settled: dict[str, Any]) -> bool:
    """Whether `settled` holds the very entries `held` does, under the same ids in the same order: the feed replaces an
    entry it changes, so this is a walk of identities where `==` would compare each entry's fields."""
    return len(held) == len(settled) and list(held) == list(settled) and all(map(is_, held.values(), settled.values()))


def _settled_day(data: dict[str, Any], held: _Held) -> _Day:
    """The settled day of `data`: the one `held` has while the feed's settled tasks, the done lanes and the 24 hours are
    as they were, else drawn now, with each task's JSON kept while the feed holds the same entry object."""
    settled, now, done = data["settled"], data["now"], done_lanes(data["roles"]["done"])
    day: _Day | None = held.get(("day",))  # type: ignore[assignment]
    if day and day.since <= now <= day.until and day.done == done and _same(day.settled, settled):
        return day
    adapter, old = _adapter(Settled), day.pairs if day else {}
    recent = recent_settled(data)
    pairs = {}
    for task_id, entry in recent.items():
        pair = old.get(task_id)
        if pair is None or pair[0] is not entry:
            dump = adapter.dump_json(adapter.validate_python(entry), by_alias=True, exclude_unset=True)
            pair = (entry, json.dumps(task_id, ensure_ascii=False).encode() + b":" + dump)
        pairs[task_id] = pair
    until = min((max(e["created"] or 0, e["at"] or 0) for e in recent.values()), default=float("inf")) + LIVE_WINDOW_S
    return _Day(dict(settled), done, now, until, pairs, settled_counts(data), b",".join(pair[1] for pair in pairs.values()))


def _dump_parts(drawn: dict[str, Any], held: _Held, kept: _Held) -> dict[str, bytes]:
    """The JSON of each `_PARTS` field `drawn` holds, the one `held` has while it is equal to the last, and `drawn` with
    the stand-in for it."""
    fields, found = BODIES["snapshot"].model_fields, {}
    for name, empty in _PARTS.items():
        value = drawn.get(name)
        if not value or value == empty:
            continue
        memo = held.get(("part", name))
        if memo is None or not (memo[0] is value or memo[0] == value):
            adapter = _adapter(fields[name].annotation)
            memo = (value, adapter.dump_json(adapter.validate_python(value), by_alias=True, exclude_unset=True))
        kept[("part", name)] = memo
        found[name], drawn[name] = memo[1], empty
    return found


class SegmentedBody(bytes):
    """A body with the pieces it was joined from, which the snapshot store compresses one by one: a piece the body has
    again is not compressed again."""

    segments: list[bytes]


def encode_snapshot(data: Any, held: _Held) -> bytes:
    """`encode("snapshot", slim_snapshot(data))`, the one body the API serves, with the JSON of each board task and
    machine agent, the settled day, and the dags, kept in `held` between calls.

    `held` maps `id(object)` to the object and its JSON (an agent under `("machine", id)`, a flow's trail names under
    `("names", flow)`, a `_PARTS` field under `("part", name)`, and the
    settled day under `("day",)`): the feed replaces a task, agent or settled entry it changes rather than editing it,
    so one met again encodes the same, and one no longer listed is forgotten. Those are most of the snapshot (the
    settled day's entries alone 3.8 of its 4.9 MB), so a build after one change validates and dumps only what changed
    and the rest of the document; the settled tasks are walked only when one changed, and met by identity otherwise.
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
    day = kept[("day",)] = _settled_day(data, held)
    drawn = {
        **slim_snapshot({**data, "flows": [{**flows[0], "agents": []}, *bare], "settled": {}}),
        "milestone_done": milestone_done(data, day.counted),
    }
    parts = _dump_parts(drawn, held, kept)
    held.clear()
    held.update(kept)
    body = encode("snapshot", drawn)
    try:
        pieces = _splice(body, [tasks, *(dumps for _, dumps in machines)], [flow["name"] for flow in flows], parts, day.dumped)
    except ValueError:  # the document is not drawn as it was: encode it whole
        return encode("snapshot", slim_snapshot(data))
    encoded = SegmentedBody(b"".join(pieces))
    encoded.segments = pieces
    return encoded


def _splice(
    body: bytes, agents: list[list[bytes]], names: list[str], parts: dict[str, bytes], settled: bytes
) -> list[bytes]:
    """`body` in pieces with each flow's empty `"agents":[]` replaced by its drawn agents, the flows taken in order, each
    `parts` stand-in by its JSON, and the empty `"settled":{}` by `settled`: a drawn piece stands alone, between the
    pieces of the rest of the body. ValueError when a stand-in is absent or not alone."""
    holes, search = [], body.index(b'"flows":[')
    for drawn, name in zip(agents, names, strict=True):
        at = body.index(b'"agents":[]', body.index(b'{"name":%s' % json.dumps(name, ensure_ascii=False).encode(), search))
        holes.append((at, len(b'"agents":[]'), b'"agents":[', b",".join(drawn), b"]"))
        search = at + len(b'"agents":[]')
    stand_ins = {b'"settled":{}': (b'"settled":{', settled, b"}")}
    for name, dump in parts.items():
        stand_ins[json.dumps({name: _PARTS[name]}, separators=(",", ":"))[1:-1].encode()] = (b'"%s":' % name.encode(), dump, b"")
    for marker, (prefix, drawn, suffix) in stand_ins.items():
        if body.count(marker) != 1:
            raise ValueError(marker.decode())
        holes.append((body.index(marker), len(marker), prefix, drawn, suffix))
    pieces, cursor, after = [], 0, b""
    for at, size, prefix, drawn, suffix in sorted(holes):
        pieces += [after + body[cursor:at] + prefix, drawn]
        cursor, after = at + size, suffix
    return [*pieces, after + body[cursor:]]
