"""Paths through a declared machine, and the strict and lenient replay of a trace against it."""

from pathlib import Path
from typing import Any

from starpulse._internal.machines.graph import (
    Accepted,
    Bypass,
    Incomplete,
    Machine,
    Step,
    Violation,
    bypasses,
    conform,
    dominators,
    fitness,
    replay,
    runs,
    shortest_paths,
    simple_paths,
)
from starpulse._internal.machines.machine_definition import compile_document

#: start -OPEN-> draft -SUBMIT-> review -APPROVE-> done; review -REJECT-> draft; draft <-SHELVE/RESUME-> shelved.
FLOW: dict[str, Any] = {
    "name": "Flow",
    "states": {"start": {"initial": True}, "draft": {}, "review": {}, "done": {"final": True}, "shelved": {}},
    "events": {
        "OPEN": [{"from": "start", "to": "draft"}],
        "SUBMIT": [{"from": "draft", "to": "review"}],
        "APPROVE": [{"from": "review", "to": "done"}],
        "REJECT": [{"from": "review", "to": "draft"}],
        "SHELVE": [{"from": "draft", "to": "shelved"}],
        "RESUME": [{"from": "shelved", "to": "draft"}],
    },
}


def _machine(document: dict[str, Any] = FLOW, rests: tuple[str, ...] = ()) -> Machine:
    chart = compile_document(document, Path("flow.yaml")).machine
    return type("Resting", (chart,), {"RESTS": rests}) if rests else chart


def _states(*ids: str) -> frozenset[str]:
    return frozenset(ids)


def test_each_reachable_state_gets_one_shortest_event_sequence() -> None:
    found = {tuple(sorted(path.state)): path.events for path in shortest_paths(_machine())}

    assert found == {
        ("start",): (),
        ("draft",): ("OPEN",),
        ("review",): ("OPEN", "SUBMIT"),
        ("done",): ("OPEN", "SUBMIT", "APPROVE"),
        ("shelved",): ("OPEN", "SHELVE"),
    }


def test_a_simple_path_never_revisits_a_state() -> None:
    found = {path.events for path in simple_paths(_machine())}

    assert found == {(), ("OPEN",), ("OPEN", "SUBMIT"), ("OPEN", "SUBMIT", "APPROVE"), ("OPEN", "SHELVE")}


def test_a_trace_that_ends_in_a_final_state_is_accepted() -> None:
    assert conform(_machine(), ("OPEN", "SUBMIT", "APPROVE")) == Accepted()


def test_the_first_event_the_state_cannot_take_is_the_violation() -> None:
    assert conform(_machine(), ("OPEN", "APPROVE", "SUBMIT")) == Violation(1, "APPROVE", _states("draft"))


def test_a_legal_trace_that_stops_short_is_incomplete() -> None:
    assert conform(_machine(), ("OPEN", "SUBMIT")) == Incomplete(_states("review"))


def test_a_state_the_machine_names_as_a_rest_settles_a_trace() -> None:
    assert conform(_machine(rests=("shelved",)), ("OPEN", "SHELVE")) == Accepted()


def test_a_lenient_replay_skips_an_illegal_event_and_judges_the_rest_from_where_it_is() -> None:
    steps = replay(_machine(), ("OPEN", "APPROVE", "SUBMIT"))

    assert steps == [
        Step("OPEN", _states("start"), _states("draft")),
        Step("APPROVE", _states("draft"), None),
        Step("SUBMIT", _states("draft"), _states("review")),
    ]
    assert fitness(steps) == 2 / 3


def test_a_trace_with_nothing_mapped_has_no_fitness() -> None:
    assert fitness([]) is None


def test_a_trace_is_cut_into_runs_at_the_restart_event_once_a_run_has_settled() -> None:
    trace = ("OPEN", "SUBMIT", "APPROVE", "SUBMIT", "OPEN", "SUBMIT")

    assert runs(_machine(), trace, "OPEN") == [("OPEN", "SUBMIT", "APPROVE"), ("OPEN", "SUBMIT")]


def test_a_dominator_is_a_node_every_route_from_the_entry_crosses() -> None:
    graph = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}

    found = dominators(graph, "a")

    assert (found["b"], found["d"]) == (frozenset("ab"), frozenset("ad"))


def test_a_gate_every_route_to_the_goal_crosses_is_not_bypassed() -> None:
    assert bypasses(_machine(), ["review"], "done") == []


def test_a_route_to_the_goal_that_avoids_the_gate_is_reported_with_a_shortest_witness() -> None:
    shortcut = {**FLOW, "events": {**FLOW["events"], "WAIVE": [{"from": "draft", "to": "done"}]}}

    assert bypasses(_machine(shortcut), ["review"], "done") == [Bypass("review", _states("done"), ("OPEN", "WAIVE"))]
