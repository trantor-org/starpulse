"""Every analytics and trace route answers from fold rows what the whole-list model functions answered over the signals
of its window, and its `history_s` is the table's oldest signal time."""

import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from starpulse.contracts.signals import Signal
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.model import cells, flow, session_health, steps, traces
from starpulse.harness_telemetry.adapters.outbound.signal_table import SignalTable
from starpulse.views.adapters.outbound.signal_folds import SignalFolds
from starpulse.views.application.queries import responses, trace_responses

from tests.unit.flow_metrics.test_folds import ANALYTICS, KEYS, TASKS, WINDOW_START, finish, history, sig, work

HOURS = 0.5
NOW = WINDOW_START + HOURS * 3600
QUERY = {"hours": [str(HOURS)]}


def titled() -> dict[str, Any]:
    return TASKS


def everything() -> list[Signal]:
    """`history()` plus what it cuts at the window's start: the first hours of the session `long`, which began before
    the window, and a lone request long before it, so the stages route's double window lies inside the history."""
    early = work("long", 9, 1100.0, ["read"] * 30 + ["edit", "test"], skill=True) + finish("long", 9, 2000.0)
    anchor = [sig("request", -4000.0, "anchor", model="m", seconds=1.0)]
    return anchor + [s for s in early if s.time < WINDOW_START] + history()


@pytest.fixture
def folds(tmp_path: Path) -> SignalFolds:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    SignalTable(log.engine).insert(asdict(s) for s in everything())
    found = SignalFolds(log, KEYS, ANALYTICS)
    found.catch_up()
    return found


def held(span: int = 1) -> list[Signal]:
    return [s for s in everything() if s.time >= NOW - span * HOURS * 3600]


def body(answer: tuple[bytes, int], label: str) -> Any:
    raw, status = answer
    assert status == 200, raw
    return json.loads(raw)[label]


def plain(rows: Any) -> Any:
    return json.loads(json.dumps(rows))


def sessions() -> list[dict[str, Any]]:
    return session_health.session_health(held(), KEYS, ANALYTICS)


#: Each route, the label its body keys the rows by, the call that answers it from fold rows, and the model function
#: over the signals of its window that it answered before.
ROUTES: dict[str, tuple[str, Callable[[SignalFolds], tuple[bytes, int]], Callable[[], Any]]] = {
    "transitions": (
        "transitions",
        lambda f: responses.transitions_response(f, QUERY, KEYS, titled, NOW, ANALYTICS),
        lambda: cells.transition_cost(held(), KEYS, TASKS, ANALYTICS),
    ),
    "cells": (
        "cells",
        lambda f: responses.cells_response(f, QUERY, KEYS, titled, NOW, ANALYTICS),
        lambda: cells.cell_report(session_health.slice_health(sessions()), TASKS),
    ),
    "estimates": (
        "estimates",
        lambda f: responses.estimates_response(f, QUERY, KEYS, titled, NOW, ANALYTICS),
        lambda: cells.estimate_report(session_health.slice_health(sessions()), TASKS, ANALYTICS.size_bands, None),
    ),
    "graph": (
        "graph",
        lambda f: responses.graph_response(f, QUERY, KEYS, titled, NOW, ANALYTICS),
        lambda: flow.directly_follows(held(), KEYS, TASKS, ANALYTICS),
    ),
    "stages": (
        "stages",
        lambda f: responses.stages_response(f, QUERY, KEYS, titled, NOW, ANALYTICS),
        lambda: flow.sub_stages(held(2), KEYS, TASKS, ANALYTICS, since=NOW - HOURS * 3600),
    ),
    "diff": (
        "diff",
        lambda f: responses.diff_response(f, QUERY, KEYS, titled, NOW, ANALYTICS),
        lambda: flow.fast_slow_diff(held(), KEYS, TASKS, ANALYTICS),
    ),
    "cost_to_go": (
        "cost_to_go",
        lambda f: responses.cost_to_go_response(f, QUERY, KEYS, titled, NOW, ANALYTICS),
        lambda: flow.cost_to_go(held(), KEYS, TASKS, ANALYTICS),
    ),
}


@pytest.mark.parametrize("route", ROUTES)
def test_a_kind_and_size_route_answers_from_fold_rows_what_the_signals_of_its_window_gave(
    folds: SignalFolds, route: str
) -> None:
    label, answer, expected = ROUTES[route]

    assert body(answer(folds), label) == plain(expected())
    assert plain(expected())  # the seeded history gives the route something to answer


def test_the_sessions_route_answers_from_fold_rows_what_the_signals_of_its_window_gave(folds: SignalFolds) -> None:
    answer = responses.sessions_response(folds, QUERY, KEYS, NOW, ANALYTICS)

    assert body(answer, "sessions") == plain(sessions())
    assert body(answer, "slices") == plain(session_health.slice_health(sessions()))
    long = [s.time for s in everything() if s.session == "long"]
    assert min(long) < NOW - HOURS * 3600 < max(long)  # a session began before the window and ran into it


def test_the_steps_route_answers_from_fold_rows_the_steps_of_the_signals_of_its_window(folds: SignalFolds) -> None:
    answer = responses.steps_response(folds, QUERY, KEYS, NOW, ANALYTICS)
    expected = steps.session_steps(held(), KEYS, ANALYTICS)

    assert [(r["harness"], r["session"], r["at"]) for r in body(answer, "steps")] == [
        (r["harness"], r["session"], r["at"]) for r in expected
    ]


@pytest.mark.parametrize("include_eval", [True, False])
def test_the_trace_cases_from_fold_rows_are_the_cases_of_the_signals_of_the_window(
    folds: SignalFolds, include_eval: bool
) -> None:
    found = trace_responses._telemetry_cases(
        folds, HOURS, KEYS, titled, ANALYTICS, NOW, "missed_loads", include_eval=include_eval
    )
    window = held() if include_eval else [s for s in held() if not s.eval]

    assert found == traces.cases(window, KEYS, roots=ANALYTICS.roots, tasks=TASKS, analytics=ANALYTICS)
    assert found


def test_a_window_past_the_history_is_400_with_the_age_of_the_tables_oldest_signal(folds: SignalFolds) -> None:
    raw, status = responses.sessions_response(folds, {"hours": ["1000"]}, KEYS, NOW, ANALYTICS)

    assert status == 400
    assert json.loads(raw)["history_s"] == NOW - min(s.time for s in everything())
    assert folds.oldest() == min(s.time for s in everything())


def test_a_table_with_no_signal_answers_a_window_past_its_empty_history(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")

    raw, status = responses.sessions_response(SignalFolds(log, KEYS, ANALYTICS), QUERY, KEYS, NOW, ANALYTICS)

    assert (status, json.loads(raw)["history_s"]) == (400, 0)
