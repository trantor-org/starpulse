"""GET /api/analytics/steps against recorded exports of both harnesses published to the event log."""

import json
import re
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.contracts.adapters import TaskKeys
from starpulse.event_log.event_log import EventLog
from starpulse.harness_telemetry.adapters.inbound.telemetry import TelemetryLog, signals
from starpulse.runtime.adapter_kit import serve, url
from starpulse.views.adapters.inbound.page_server import PageServer

from tests.machines import MACHINES, ROLES
from tests.unit.harness_telemetry.test_telemetry import FIXTURES

KEYS = TaskKeys(
    key=re.compile(r"TASK-\d+"),
    branch=re.compile(r"(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", re.IGNORECASE),
    key_format="TASK-{}",
)
#: An hour after the recorded exports.
NOW = datetime.fromisoformat("2026-10-09T22:30:00+00:00").timestamp()


def _get(server: PageServer, query: str = "") -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"/api/analytics/steps{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture
def server(tmp_path: Path) -> Iterator[PageServer]:
    telemetry = TelemetryLog(EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))
    for name in ("claude_code/otlp.ndjson", "codex/otlp.ndjson"):
        for line in (FIXTURES / name).read_text().splitlines():
            telemetry.publish(signals(json.loads(line)))
    with serve(
        tmp_path, BoardFeed(roles=ROLES, machines=MACHINES, keys=KEYS), telemetry=telemetry, clock=lambda: NOW
    ) as server:
        yield server


def test_every_model_request_of_both_harnesses_is_a_step_oldest_first(server: PageServer) -> None:
    status, body = _get(server, "?hours=1.06")

    assert status == 200
    assert (body["now"], body["window_s"]) == (NOW, 1.06 * 3600)
    steps = body["steps"]
    assert [(s["harness"], s["task"], s["captured"]) for s in steps] == [
        *[("claude-code", "TASK-1", True)] * 3,
        *[("codex", None, False)] * 3,
    ]
    assert [s["at"] for s in steps] == sorted(s["at"] for s in steps)
    assert {s["skill"] for s in steps} == {"none"}
    claude = steps[0]
    assert (claude["model"], claude["origin"], set(claude["tokens"])) == (
        "claude-sonnet-5-5",
        "main",
        {"input", "output", "cache_read", "cache_write", "reasoning"},
    )
    # The recorded commands are `echo`, which the activity vocabulary leaves out, and the adapter ran with no
    # redactor, so a call is keyed by its tool's name.
    assert [(s["activities"], s["keys"]) for s in steps[:3]] == [([], ["Bash"]), ([], ["Bash"]), ([], [])]


def test_the_window_defaults_to_a_week_which_a_short_history_refuses_and_leaves_out_what_happened_before_it(
    server: PageServer,
) -> None:
    week_status, week = _get(server)
    _, minutes = _get(server, "?hours=0.01")
    _, inside = _get(server, "?hours=1.06")

    assert (week_status, "168 hours" in week["error"]) == (400, True)
    assert (len(inside["steps"]), minutes["steps"]) == (6, [])


@pytest.mark.parametrize("query", ["?hours=0", "?hours=-1", "?hours=soon", "?hours=nan", "?hours=inf"])
def test_a_window_that_is_not_a_positive_number_is_refused(server: PageServer, query: str) -> None:
    status, body = _get(server, query)

    assert (status, "positive number" in body["error"]) == (400, True)


def test_an_instance_that_receives_no_telemetry_cannot_report_steps(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES, keys=KEYS)) as server:
        status, body = _get(server)

    assert (status, "telemetry" in body["error"]) == (501, True)


def test_a_window_longer_than_the_telemetry_history_is_refused_with_the_history_s_and_a_shorter_one_is_answered(
    server: PageServer,
) -> None:
    status, refused = _get(server, "?hours=24")
    _, history = _get(server, "?hours=0.5")

    assert (status, 3000 < refused["history_s"] < 4 * 3600, "longer than the history" in refused["error"]) == (
        400,
        True,
        True,
    )
    assert history["window_s"] == 1800
