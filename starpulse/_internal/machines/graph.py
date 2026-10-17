"""Generated paths through a declared machine, and strict conformance of a trace to it.

A machine is a `python-statemachine` `StateChart`, passed as a zero-argument factory: the class itself (what
`machine_definition.load_machine` compiles a `.starpulse/machines/` file to), or a function that builds it around a
fresh model when its guards read extended state. Every snapshot is reached by replaying events on a new instance, so
guards run exactly as they would in use.

Extended state lives on the machine's model. Two snapshots are the same state only when their configuration and their
model's attributes both match, so a guard's input distinguishes paths the configuration alone cannot.

A machine may name `RESTS`: states a procedure ends in though an event leaves them. A trace settles in a rest as it does
in a final state.
"""

from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from statemachine import StateChart

type Machine = Callable[[], StateChart]


class Snapshot(NamedTuple):
    """A machine's configuration and its model's attributes: two snapshots are the same state only when both match."""

    state: frozenset[str]
    model: str


@dataclass(frozen=True)
class Path:
    """The events of one route, and the state it ends in."""

    events: tuple[str, ...]
    state: frozenset[str]


@dataclass(frozen=True)
class Accepted:
    """The trace ended in a final state or a rest."""


@dataclass(frozen=True)
class Violation:
    """The first event the current state cannot take; the replay stops there."""

    step: int
    event: str
    state: frozenset[str]


@dataclass(frozen=True)
class Incomplete:
    """Every event was legal, but the trace ended outside a final state or a rest."""

    state: frozenset[str]


type Verdict = Accepted | Violation | Incomplete


@dataclass(frozen=True)
class Bypass:
    """A route to `target` that never enters `gate`: the events of one shortest such route."""

    gate: str
    target: frozenset[str]
    witness: tuple[str, ...]


@dataclass(frozen=True)
class Step:
    """One replayed event: the state it left, and the state it reached if it was legal."""

    event: str
    source: frozenset[str]
    target: frozenset[str] | None

    @property
    def legal(self) -> bool:
        return self.target is not None


def _replay(new: Machine, events: Iterable[str]) -> StateChart:
    machine = new()
    for event in events:
        machine.send(event)
    return machine


def _state(machine: StateChart) -> frozenset[str]:
    return frozenset(state.id for state in machine.configuration)


def _key(machine: StateChart) -> Snapshot:
    return Snapshot(_state(machine), repr(sorted(vars(machine.model).items())))


def _settled(machine: StateChart) -> bool:
    """Whether the machine is in a final state or one of the rests it names."""
    return machine.is_terminated or not _state(machine).isdisjoint(getattr(machine, "RESTS", ()))


def _enabled(machine: StateChart) -> list[str]:
    """The events the current snapshot can take, its guards included."""
    return [event.id for event in machine.enabled_events()]


def shortest_paths(new: Machine) -> list[Path]:
    """One shortest event sequence to each reachable state, in breadth-first order."""
    found: dict[tuple[frozenset[str], str], Path] = {}
    queue: deque[tuple[str, ...]] = deque([()])
    while queue:
        events = queue.popleft()
        machine = _replay(new, events)
        key = _key(machine)
        if key in found:
            continue
        found[key] = Path(events, _state(machine))
        queue.extend((*events, event) for event in _enabled(machine))
    return list(found.values())


def simple_paths(new: Machine) -> list[Path]:
    """Every event sequence that reaches a state without revisiting one."""
    found: list[Path] = []

    def walk(events: tuple[str, ...], visited: frozenset[tuple[frozenset[str], str]]) -> None:
        machine = _replay(new, events)
        key = _key(machine)
        if key in visited:
            return
        found.append(Path(events, _state(machine)))
        for event in _enabled(machine):
            walk((*events, event), visited | {key})

    walk((), frozenset())
    return found


def conform(new: Machine, events: Iterable[str]) -> Verdict:
    """Replay a mapped trace strictly."""
    machine = new()
    for step, event in enumerate(events):
        if event not in _enabled(machine):
            return Violation(step, event, _state(machine))
        machine.send(event)
    return Accepted() if _settled(machine) else Incomplete(_state(machine))


def replay(new: Machine, events: Iterable[str]) -> list[Step]:
    """Replay a mapped trace leniently: an illegal event is recorded and skipped,
    so every later event is still judged from the state the machine is actually in.
    `conform` is the strict verdict; this is the per-event record beside it."""
    machine = new()
    steps = []
    for event in events:
        source = _state(machine)
        if event in _enabled(machine):
            machine.send(event)
            steps.append(Step(event, source, _state(machine)))
        else:
            steps.append(Step(event, source, None))
    return steps


def runs(new: Machine, events: Iterable[str], restart: str) -> list[tuple[str, ...]]:
    """Cut a mapped trace into the runs of one procedure, replayed leniently as `replay` does.

    A run ends when the machine reaches a final state or a rest. What the trace does after that repeats a finished
    procedure, so it belongs to no run until `restart` begins the next one; the first run begins at the
    first event, whatever it is. An illegal event stays in its run for `conform` to judge."""
    found: list[list[str]] = []
    machine = None
    for event in events:
        if machine is None:
            if found and event != restart:
                continue
            found.append([])
            machine = new()
        found[-1].append(event)
        if event in _enabled(machine):
            machine.send(event)
            if _settled(machine):
                machine = None
    return [tuple(run) for run in found]


def fitness(steps: Sequence[Step]) -> float | None:
    """Legal steps over mapped steps of a lenient replay, beside `conform`'s verdict.

    A trace that stopped short scores 1.0 if every step it took was legal, so this
    measures legality of what was observed, never completeness. `None` when nothing
    was mapped: no evidence is not a perfect score."""
    if not steps:
        return None
    return sum(step.legal for step in steps) / len(steps)


def dominators[N](successors: Mapping[N, Iterable[N]], entry: N) -> dict[N, frozenset[N]]:
    """Each node's dominators: the nodes every route from `entry` to it crosses, itself included.

    The iterative fixed point; every node of `successors` must be reachable from `entry`."""
    predecessors: defaultdict[N, set[N]] = defaultdict(set)
    for node, targets in successors.items():
        for target in targets:
            predecessors[target].add(node)
    nodes = frozenset(successors)
    dominated = dict.fromkeys(nodes, nodes) | {entry: frozenset({entry})}
    while True:
        changed = {}
        for node in nodes - {entry}:
            update = frozenset.intersection(*(dominated[p] for p in predecessors[node])) | {node}
            if update != dominated[node]:
                changed[node] = update
        if not changed:
            return dominated
        dominated |= changed


def _transitions(new: Machine) -> tuple[Snapshot, dict[Snapshot, tuple[tuple[str, Snapshot], ...]]]:
    """The entry snapshot, and each reachable snapshot's `(event, snapshot)` hops in breadth-first order."""
    entry = _key(new())
    hops: dict[Snapshot, tuple[tuple[str, Snapshot], ...]] = {}
    queue: deque[tuple[tuple[str, ...], Snapshot]] = deque([((), entry)])
    while queue:
        events, key = queue.popleft()
        if key in hops:
            continue
        machine = _replay(new, events)
        steps = []
        for event in _enabled(machine):
            steps.append((event, _key(_replay(new, (*events, event)))))
        hops[key] = tuple(steps)
        queue.extend(((*events, event), target) for event, target in hops[key])
    return entry, hops


def bypasses(new: Machine, gates: Iterable[str], goal: str) -> list[Bypass]:
    """Every gate state some route to a `goal` state avoids, with one shortest route that avoids it.

    A gate is mandatory when it dominates the goal, so its snapshots are merged into one node before
    the dominators run: a route through any of them has crossed the gate. A goal snapshot that
    holds the gate itself is never a bypass of it, nor is any goal of a machine that starts in it."""
    entry, hops = _transitions(new)
    findings = []
    for gate in gates:
        if gate in entry.state:
            continue

        def fold(key: Snapshot, gate: str = gate) -> Snapshot | str:
            return gate if gate in key.state else key

        merged: defaultdict[Snapshot | str, set[Snapshot | str]] = defaultdict(set)
        for key, out in hops.items():
            merged[fold(key)] |= {fold(target) for _, target in out}
        crossed = dominators(merged, entry)
        witnesses = _avoiding(hops, entry, gate)
        reported: set[frozenset[str]] = set()
        for key in hops:
            if goal in key.state and gate not in crossed[fold(key)] and key.state not in reported:
                reported.add(key.state)
                findings.append(Bypass(gate, key.state, witnesses[key]))
    return findings


def _avoiding(
    hops: Mapping[Snapshot, tuple[tuple[str, Snapshot], ...]], entry: Snapshot, gate: str
) -> dict[Snapshot, tuple[str, ...]]:
    """The events of a shortest route from `entry` to each snapshot reachable without entering `gate`."""
    routes: dict[Snapshot, tuple[str, ...]] = {entry: ()}
    queue = deque(routes)
    while queue:
        key = queue.popleft()
        for event, target in hops[key]:
            if target not in routes and gate not in target.state:
                routes[target] = (*routes[key], event)
                queue.append(target)
    return routes
