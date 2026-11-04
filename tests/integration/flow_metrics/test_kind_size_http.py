"""GET /api/analytics/transitions and /api/analytics/cells against recorded exports published to the event log."""

import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.harness_telemetry.adapters.inbound.telemetry import signals
from starpulse.runtime.adapter_kit import serve, url
from starpulse.views.adapters.inbound.page_server import PageServer
from starpulse.views.application.queries.answers import Answers

from tests.folded_telemetry import FoldedTelemetry
from tests.machines import MACHINES, ROLES
from tests.unit.flow_metrics.test_flow import EXECUTE_8, WORK_STEPS, completed
from tests.unit.harness_telemetry.test_telemetry import FIXTURES

KEYS = TaskKeys(
    key=re.compile(r"TASK-\d+"),
    branch=re.compile(r"(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", re.IGNORECASE),
    key_format="TASK-{}",
)
NOW = datetime.fromisoformat("2026-10-09T22:30:00+00:00").timestamp()
ROUTES = pytest.mark.parametrize("route", ["transitions", "cells", "graph", "diff", "stages"])


def _get(server: PageServer, route: str, query: str = "") -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"/api/analytics/{route}{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _published(telemetry: FoldedTelemetry) -> FoldedTelemetry:
    for name in ("claude_code/otlp.ndjson", "codex/otlp.ndjson"):
        for line in (FIXTURES / name).read_text().splitlines():
            telemetry.publish(signals(json.loads(line)))
    return telemetry


@pytest.fixture
def server(tmp_path: Path) -> Iterator[PageServer]:
    telemetry = _published(FoldedTelemetry(tmp_path, KEYS))
    with serve(
        tmp_path, BoardFeed(roles=ROLES, machines=MACHINES, keys=KEYS), telemetry=telemetry, clock=lambda: NOW
    ) as server:
        yield server


@ROUTES
def test_a_report_with_no_labelled_task_is_empty_inside_the_history(server: PageServer, route: str) -> None:
    hours = 0.5 if route == "stages" else 1.06  # stages also reads the window before
    status, body = _get(server, route, f"?hours={hours}")

    assert (status, body) == (200, {"now": NOW, "window_s": hours * 3600, route: []})


def test_the_stages_report_needs_the_history_to_hold_the_window_before_too(server: PageServer) -> None:
    status, body = _get(server, "stages", "?hours=1.06")

    assert (status, "longer than the history" in body["error"]) == (400, True)


@ROUTES
def test_a_window_past_the_history_or_that_is_no_positive_number_is_refused(server: PageServer, route: str) -> None:
    past, longer = _get(server, route, "?hours=24")
    bad, _ = _get(server, route, "?hours=0")

    assert (past, bad, "longer than the history" in longer["error"]) == (400, 400, True)


@ROUTES
def test_an_instance_that_receives_no_telemetry_cannot_report(tmp_path: Path, route: str) -> None:
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES, keys=KEYS)) as server:
        status, body = _get(server, route)

    assert (status, "telemetry" in body["error"]) == (501, True)


def test_cost_to_go_is_served_per_state_with_the_times_the_state_was_left(tmp_path: Path) -> None:
    runs = [("read", "edit", "test"), ("edit", "test"), ("edit", "edit", "test"), ("edit", "test", "read")]
    analytics = Analytics(
        completion_skill="completing-tasks", stop_activities=frozenset({"Skill"}), skill_machines=(WORK_STEPS,)
    )
    telemetry = FoldedTelemetry(tmp_path, KEYS, analytics)
    for n, calls in enumerate(runs, 1):
        telemetry.publish(completed(n, *calls))
    feed = BoardFeed(roles=ROLES, machines=MACHINES, keys=KEYS)
    feed.titled = lambda: {f"TASK-{n}": EXECUTE_8 for n in range(1, 5)}  # type: ignore[method-assign]
    with serve(tmp_path, feed, telemetry=telemetry, clock=lambda: 4600.0, analytics=analytics) as server:
        status, body = _get(server, "cost-to-go", "?hours=1")

    rows = [r for r in body["cost_to_go"] if r["skill"] == "work"]
    assert (status, body["now"], body["window_s"]) == (200, 4600.0, 3600.0)
    assert [(r["kind"], r["size"], r["state"], r["n"], round(r["cost_to_go"], 2)) for r in rows] == [
        ("execute", 8, "[start]", 4, 2.75),
        ("execute", 8, "edit", 4, 1.5),
        ("execute", 8, "test", 1, 1.0),
    ]


def test_cost_to_go_is_empty_inside_the_history_and_refused_past_it(server: PageServer) -> None:
    inside = _get(server, "cost-to-go", "?hours=1.06")
    past = _get(server, "cost-to-go", "?hours=24")

    assert inside == (200, {"now": NOW, "window_s": 1.06 * 3600, "cost_to_go": []})
    assert (past[0], "longer than the history" in past[1]["error"]) == (400, True)


def test_a_restarted_instance_answers_a_report_from_the_saved_answer_before_it_reads_any_telemetry(
    tmp_path: Path,
) -> None:
    telemetry = _published(FoldedTelemetry(tmp_path, KEYS))
    log = telemetry.events
    first = Answers(log.engine)
    feed = BoardFeed(roles=ROLES, machines=MACHINES, keys=KEYS)
    with serve(tmp_path, feed, telemetry=telemetry, clock=lambda: NOW, answers=first) as server:
        before = _get(server, "cells", "?hours=1.06")
    first.join()

    with serve(tmp_path, feed, clock=lambda: NOW, answers=Answers(log.engine)) as restarted:
        after = _get(restarted, "cells", "?hours=1.06")
        other = _get(restarted, "cells", "?hours=2")

    assert (before, after, other[0]) == ((200, {"now": NOW, "window_s": 3816.0, "cells": []}),) * 2 + (501,)


def test_a_window_past_the_history_is_refused_while_a_fold_of_another_query_runs(tmp_path: Path) -> None:
    """TASK-11099: a refusal needs no fold, so it never queues behind the one fold at a time that a refold holds."""
    telemetry = _published(FoldedTelemetry(tmp_path, KEYS))
    answers = Answers(telemetry.events.engine)
    folding, release = threading.Event(), threading.Event()

    def refold() -> tuple[bytes, int]:
        folding.set()
        release.wait(8)
        return b"{}", 200

    threading.Thread(target=answers.answer, args=("/api/analytics/cells", "other", refold), daemon=True).start()
    assert folding.wait(10)
    feed = BoardFeed(roles=ROLES, machines=MACHINES, keys=KEYS)
    with serve(tmp_path, feed, telemetry=telemetry, clock=lambda: NOW, answers=answers) as server:
        started = time.monotonic()
        try:
            past = _get(server, "diff", "?hours=24")
        except OSError:  # the request outwaited the client's timeout: still queued behind the fold
            past = (0, {})
        waited = time.monotonic() - started
    release.set()
    answers.join()

    assert (past[0], "longer than the history" in past[1].get("error", ""), waited < 2) == (400, True, True)


def test_estimates_carry_each_completed_tasks_label_beside_its_measured_effort(tmp_path: Path) -> None:
    analytics = Analytics(completion_skill="completing-tasks", size_bands=((1, 2, 5.0), (3, 10, 5.0), (8, 100, 50.0)))
    telemetry = FoldedTelemetry(tmp_path, KEYS, analytics)
    for n in (1, 2):
        telemetry.publish(completed(n, "read", "edit", "test"))
    feed = BoardFeed(roles=ROLES, machines=MACHINES, keys=KEYS)
    profile = "@agent-standard-high"
    feed.titled = lambda: {  # type: ignore[method-assign]
        "TASK-1": {"labels": ["kind-execute", "size-8"], "milestone": "m-305", "profile": profile},
        "TASK-2": {"labels": ["kind-execute", "size-1"], "milestone": "m-9", "profile": profile},
    }
    with serve(tmp_path, feed, telemetry=telemetry, clock=lambda: 4600.0, analytics=analytics) as server:
        every = _get(server, "estimates", "?hours=1")
        one = _get(server, "estimates", "?hours=1&milestone=m-305")

    rows = {r["task"]: r for r in every[1]["estimates"]}
    assert (every[0], one[0]) == (200, 200)
    assert {t: (r["milestone"], r["kind"], r["size"], r["profile"]) for t, r in rows.items()} == {
        "TASK-1": ("m-305", "execute", 8, profile),
        "TASK-2": ("m-9", "execute", 1, profile),
    }
    assert {t: (r["steps"], r["active_minutes"], r["effort_size"], r["effort_size_step"]) for t, r in rows.items()} == {
        "TASK-1": (4, 0.0, 3, -1),
        "TASK-2": (4, 0.0, 3, 1),
    }
    assert [r["task"] for r in one[1]["estimates"]] == ["TASK-1"]


def test_the_spend_report_lists_each_tasks_phases_with_no_norm_for_an_unlabelled_task(server: PageServer) -> None:
    status, body = _get(server, "spend", "?hours=1.06")

    (row,) = body["spend"]
    assert (status, body["now"], body["window_s"]) == (200, NOW, 1.06 * 3600)
    assert (row["task"], row["phase"], row["steps"], row["kind"], row["size"]) == ("TASK-1", "implement", 3, None, None)
    assert (row["wte"], row["task_wte"], row["norm_wte"], row["above_norm"]) == (
        pytest.approx(50645.95),
        pytest.approx(50645.95),
        None,
        False,
    )
