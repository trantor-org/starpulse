"""How each lifecycle machine is entered, where it nests, when it was last active and what is stuck in it.

The page draws the In Progress machine across the top and every machine entered from it as a row. A machine's
**ties** say where it is entered from: *declared* by a `SubFlow` on another machine's state, *observed* from the
trails (the state a task held on the machine it came from when its session entered this one, counted), or a *dag*
launch. Its **parent** is the machine its leading tie enters it from, else the In Progress machine; **last** and
**stuck** roll up from the machine and every machine nested below it.

`derive` is pure over the snapshot's `flows`, so the same tasks and the same clock always give the same answer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = ["STUCK_S", "derive", "entries", "page", "rows"]

#: A task idle in a working state for longer than this (seconds) is stuck.
STUCK_S = 7200
#: How long before a session entered a sibling session of the same task still counts as open (seconds).
_OPEN_S = 600
#: A declared tie outranks any count of observed ones.
_DECLARED = 1_000_000


def derive(flows: Sequence[Mapping[str, Any]], now: float) -> dict[str, dict]:
    """Each machine's `ties`, `parent`, `depth`, `chain`, `nested`, `last` and `stuck`, by machine name.

    The In Progress machine is the Board's first sub-flow; with none, no machine nests and every `parent` is None.
    A tie is `{kind, machine, state, count, dag, when}`: `machine` and `state` name where it enters from (None for a
    DAG launch, which names `dag` instead), `count` is the sessions entered through it (None for a launch, which
    the machine events do not count). A machine's ties lead with the declared one, then the most observed, then the
    launches; the first non-launch tie is the leading one. `chain` is the machines above it outermost first and
    `nested` every machine below it; `last` is None for a machine with no task. `stuck` is the task idle longest
    past `STUCK_S` outside a final state, as `{machine, state, since}` with `since` the time of its last move.
    """
    machines = {f["name"]: f for f in flows if f["name"] != "board"}
    board = next((f["machine"] for f in flows if f["name"] == "board"), {})
    first = (board.get("subflows") or [{}])[0].get("flow")
    ip = first if first in machines else None

    ties = _Ties()
    for name, f in machines.items():
        for link in f["machine"].get("subflows", []):
            if link["flow"] in machines and link["flow"] != ip:
                ties.add(link["flow"], name, link["state"], "declared", None, link.get("when", ""))
    _observe(ties, machines, ip)
    for dag, launch in (board.get("launches") or {}).items():
        if child := next((n for n in (launch.get("flow"), launch.get("skill")) if n in machines), None):
            ties.add(child, None, None, "dag", dag)

    leading = {n: ties.leading(n) for n in machines if n != ip}
    up = _nesting(machines, ip, leading)
    kids = {name: [c for c in machines if c != ip and up[c] == name] for name in (ip, *machines)}

    def below(name: str) -> list[str]:
        return [d for c in kids.get(name, []) for d in (c, *below(c))]

    def chain(name: str) -> list[str]:
        return [] if up[name] in (None, ip) else [*chain(up[name]), up[name]]

    return {
        name: {
            "ties": ties.of(name),
            "parent": None if name == ip else up[name],
            "depth": 0 if name == ip else len(chain(name)) + 1,
            "chain": [] if name == ip else chain(name),
            "nested": below(name),
            **_activity(machines, [name, *below(name)], now),
        }
        for name in machines
    }


class _Ties:
    """Every tie found, one per (child, kind, machine, state, dag), in the order they were found."""

    def __init__(self) -> None:
        self._all: dict[tuple, dict] = {}

    def add(
        self, child: str, machine: str | None, state: str | None, kind: str, dag: str | None, when: str = ""
    ) -> dict:
        return self._all.setdefault(
            (child, kind, machine, state, dag),
            {
                "kind": kind,
                "machine": machine,
                "state": state,
                "count": None if kind == "dag" else 0,
                "dag": dag,
                "when": when,
            },
        )

    def get(self, child: str, kind: str, machine: str | None, state: str | None) -> dict | None:
        return self._all.get((child, kind, machine, state, None))

    def of(self, child: str) -> list[dict]:
        found = [(key[0], tie) for key, tie in self._all.items() if key[0] == child]
        by_rank = sorted((t for _, t in found if t["kind"] != "dag"), key=lambda t: -_rank(t))
        return [*by_rank, *(t for _, t in found if t["kind"] == "dag")]

    def leading(self, child: str) -> dict | None:
        return next((t for t in self.of(child) if t["kind"] != "dag"), None)


def _rank(tie: dict) -> int:
    return _DECLARED if tie["kind"] == "declared" else tie["count"]


def _observe(ties: _Ties, machines: Mapping[str, Mapping[str, Any]], ip: str | None) -> None:
    """Count each task's session on a machine against the state its task held on the session it was entered from."""
    sessions = _sessions(machines)
    for name, f in machines.items():
        if name == ip:
            continue
        for agent in f["agents"]:
            if not agent.get("task") or not (origin := _entered_from(agent, name, sessions[agent["task"]], ip)):
                continue
            machine, state = origin
            tie = ties.get(name, "declared", machine, state) or ties.add(name, machine, state, "observed", None)
            tie["count"] += 1


def _sessions(machines: Mapping[str, Mapping[str, Any]]) -> dict[str, list[tuple[str, dict]]]:
    """Every task's sessions as (machine, session)."""
    sessions: dict[str, list[tuple[str, dict]]] = {}
    for name, f in machines.items():
        for agent in f["agents"]:
            if agent.get("task"):
                sessions.setdefault(agent["task"], []).append((name, agent))
    return sessions


def _start(agent: Mapping[str, Any]) -> float:
    trail = agent.get("trail") or []
    return trail[0]["at"] if trail else agent.get("active", 0)


def _state_at(agent: Mapping[str, Any], at: float) -> str | None:
    state = None
    for step in agent.get("trail") or []:
        if step["at"] <= at:
            state = step["state"]
    return state


def _entered_from(
    agent: Mapping[str, Any], name: str, sessions: list[tuple[str, dict]], ip: str | None
) -> tuple[str, str] | None:
    """The machine and state a new session was entered from: the newest other session still open then, else the task's In Progress one."""
    began = _start(agent)
    others = [(m, b) for m, b in sessions if b is not agent and m != name]
    open_ = sorted(
        ((m, b) for m, b in others if m != ip and _start(b) <= began and b.get("active", 0) >= began - _OPEN_S),
        key=lambda mb: -_start(mb[1]),
    )
    parent = open_[0] if open_ else next(((m, b) for m, b in others if m == ip), None)
    if parent is None:
        return None
    machine, session = parent
    trail = session.get("trail") or []
    return machine, _state_at(session, began) or (trail[0]["state"] if trail else session["state"])


def _nesting(
    machines: Mapping[str, Any], ip: str | None, leading: Mapping[str, dict | None]
) -> dict[str | None, str | None]:
    """Each machine's parent: where its leading tie enters it from, else the In Progress machine; a loop breaks to the latter."""
    up: dict[str | None, str | None] = {}
    for name in machines:
        origin = (leading.get(name) or {}).get("machine")
        up[name] = origin if origin and origin != name and origin in machines and origin != ip else ip
    for name in machines:
        if name == ip:
            continue
        seen, parent = 0, up[name]
        while parent not in (ip, None, name) and seen < len(machines):
            parent, seen = up[parent], seen + 1
        if parent == name:
            up[name] = ip
    return up


def _activity(machines: Mapping[str, Mapping[str, Any]], names: Sequence[str], now: float) -> dict:
    """When the newest task of `names` last moved, and the one idle longest past `STUCK_S` outside a final state."""
    last: float | None = None
    stuck: tuple[float, str, str] | None = None
    for name in names:
        final = {s["id"] for s in machines[name]["machine"]["states"] if s["final"]}
        for agent in machines[name]["agents"]:
            active = agent.get("active")
            if active is None:
                continue
            last = active if last is None else max(last, active)
            if agent["state"] not in final and now - active > STUCK_S and (stuck is None or active < stuck[0]):
                stuck = (active, name, agent["state"])
    return {
        "last": last,
        "stuck": None if stuck is None else {"machine": stuck[1], "state": stuck[2], "since": stuck[0]},
    }


def _activity_of(derived: Mapping[str, Mapping[str, Any]], name: str) -> float:
    return derived[name]["last"] or 0.0


def rows(derived: Mapping[str, Mapping[str, Any]], open_: str | None) -> list[str]:
    """The machines entered from `open_` (their `parent`), newest rolled-up activity first, then by name; a machine
    with no task has no activity and comes last."""
    return sorted((n for n, d in derived.items() if d["parent"] == open_), key=lambda n: (-_activity_of(derived, n), n))


def page(
    derived: Mapping[str, Mapping[str, Any]], open_: str | None, *, before: float | None, limit: int
) -> tuple[list[str], bool]:
    """The next `limit` rows of `open_` with activity older than `before` (None: the newest), and whether older remain.

    `before` is the activity of the last row the reader holds (0 for a machine with none). A page ends only between two
    different activities, so rows sharing the boundary travel together and the next page, which starts strictly older,
    neither repeats nor skips one; such a page may hold more than `limit`.
    """
    live = [n for n in rows(derived, open_) if before is None or _activity_of(derived, n) < before]
    end = limit
    while 0 < end < len(live) and _activity_of(derived, live[end]) == _activity_of(derived, live[end - 1]):
        end += 1
    return live[:end], end < len(live)


def entries(
    flows: Sequence[Mapping[str, Any]], derived: Mapping[str, Mapping[str, Any]], now: float, span: float
) -> list[dict]:
    """Every machine entry of the last `span` seconds, oldest first: a session starting in a machine other than the
    In Progress one, as `{at, machine, row, from, dag}`.

    `row` is the machine on the In Progress level it lands on, so an entry into a nested machine counts on the row
    above it. A task's session names `from` as `{machine, state}` (None when no earlier session of the task is
    known); a session with no task is a DAG launch and names the `dag` that launches its machine.
    """
    machines = {f["name"]: f for f in flows if f["name"] in derived}
    ip = next((n for n, d in derived.items() if d["depth"] == 0), None)
    sessions = _sessions(machines)
    found = []
    for name, f in machines.items():
        if name == ip:
            continue
        dag = next((t["dag"] for t in derived[name]["ties"] if t["kind"] == "dag"), None)
        for agent in f["agents"]:
            at = _start(agent)
            if not now - span <= at <= now:
                continue
            origin = _entered_from(agent, name, sessions[agent["task"]], ip) if agent.get("task") else None
            found.append(
                {
                    "at": at,
                    "machine": name,
                    "row": (derived[name]["chain"] or [name])[0],
                    "from": None if origin is None else {"machine": origin[0], "state": origin[1]},
                    "dag": None if agent.get("task") else dag,
                }
            )
    return sorted(found, key=lambda e: (e["at"], e["machine"]))
