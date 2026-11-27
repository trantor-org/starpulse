"""How each lifecycle machine is entered, where it nests, when it was last active and what is stuck in it.

The page draws the In Progress machine across the top and every machine entered from it as a row. A machine's
**ties** say where it is entered from: *declared* by a `Submachine` on another machine's state, or a *dag* launch.
Its **parent** is the machine its declared tie enters it from, else the In Progress machine; **last** and
**stuck** roll up from the machine and every machine nested below it.

`derive` is pure over the snapshot's `flows`, so the same tasks and the same clock always give the same answer.
"""

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = ["STUCK_S", "derive"]

#: A task idle in a working state for longer than this (seconds) is stuck.
STUCK_S = 7200


def derive(flows: Sequence[Mapping[str, Any]], now: float) -> dict[str, dict]:
    """Each machine's `ties`, `parent`, `depth`, `chain`, `nested`, `last` and `stuck`, by machine name.

    The In Progress machine is the Board's first submachine; with none, no machine nests and every `parent` is None.
    A tie is `{kind, machine, state, dag, when}`: `machine` and `state` name where it enters from (None for a
    DAG launch, which names `dag` instead). A machine's ties lead with the declared ones, then the launches; the
    first declared tie is the leading one. `chain` is the machines above it outermost first and
    `nested` every machine below it; `last` is None for a machine with no task. `stuck` is the task idle longest
    past `STUCK_S` outside a final state, as `{machine, state, since}` with `since` the time of its last move.
    """
    machines = {f["name"]: f for f in flows if f["name"] != "board"}
    board = next((f["machine"] for f in flows if f["name"] == "board"), {})
    first = (board.get("submachines") or [{}])[0].get("machine")
    ip = first if first in machines else None

    ties = _Ties()
    for name, f in machines.items():
        for link in f["machine"].get("submachines", []):
            if link["machine"] in machines and link["machine"] != ip:
                ties.add(link["machine"], name, link["state"], "declared", None, link.get("when", ""))
    for dag, launch in (board.get("launches") or {}).items():
        if child := next((n for n in (launch.get("machine"), launch.get("skill")) if n in machines), None):
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
                "dag": dag,
                "when": when,
            },
        )

    def of(self, child: str) -> list[dict]:
        found = [tie for key, tie in self._all.items() if key[0] == child]
        return [*(t for t in found if t["kind"] != "dag"), *(t for t in found if t["kind"] == "dag")]

    def leading(self, child: str) -> dict | None:
        return next((t for t in self.of(child) if t["kind"] != "dag"), None)


def _nesting(
    machines: Mapping[str, Any], ip: str | None, leading: Mapping[str, dict | None]
) -> dict[str | None, str | None]:
    """Each machine's parent: where its leading tie enters it from, else the In Progress machine; a loop breaks to the latter."""
    if ip is None:
        return dict.fromkeys(machines)
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
