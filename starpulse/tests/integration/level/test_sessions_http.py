"""GET /api/analytics/sessions against recorded exports of both harnesses published to the event log."""

import json
import math
import re
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from starpulse import sessions
from starpulse._internal.config.analytics import Analytics
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.harnesses.telemetry import Signal, TelemetryLog, signals
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse._internal.server.page_server import PageServer
from starpulse.contracts.adapters import TaskKeys
from starpulse.tests.machines import MACHINES, ROLES
from starpulse.tests.unit.harnesses.test_telemetry import FIXTURES

KEYS = TaskKeys(
    key=re.compile(r"TASK-\d+"),
    branch=re.compile(r"(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", re.IGNORECASE),
    key_format="TASK-{}",
)
#: An hour after the recorded exports.
NOW = datetime.fromisoformat("2026-10-09T22:30:00+00:00").timestamp()


def _get(server: PageServer, query: str = "") -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"/api/analytics/sessions{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def publish_recorded(telemetry: TelemetryLog) -> None:
    for name in ("claude_code/otlp.ndjson", "codex/otlp.ndjson"):
        for line in (FIXTURES / name).read_text().splitlines():
            telemetry.publish(signals(json.loads(line)))


@pytest.fixture
def telemetry(tmp_path: Path) -> TelemetryLog:
    return TelemetryLog(EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))


@pytest.fixture
def server(tmp_path: Path, telemetry: TelemetryLog) -> Iterator[PageServer]:
    publish_recorded(telemetry)
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES, keys=KEYS), telemetry=telemetry, clock=lambda: NOW) as server:
        yield server


def test_both_harnesses_sessions_are_served_with_the_slice_their_branch_names(server: PageServer) -> None:
    status, body = _get(server, "?hours=1.06")

    assert status == 200
    assert {(s["harness"], s["task"], s["kind"]) for s in body["sessions"]} == {
        ("claude-code", "TASK-1", "headless"),
        ("codex", None, "headless"),
    }
    (slice_,) = body["slices"]
    assert (slice_["task"], slice_["sessions"], slice_["steps"], slice_["clean"]) == ("TASK-1", 1, 3, True)
    assert (body["now"], body["window_s"]) == (NOW, 1.06 * 3600)


def test_the_window_defaults_to_a_week_which_a_short_history_refuses_and_leaves_out_what_happened_before_it(
    server: PageServer,
) -> None:
    week_status, week = _get(server)
    _, minutes = _get(server, "?hours=0.01")

    assert (week_status, "168 hours" in week["error"]) == (400, True)
    assert (minutes["sessions"], minutes["slices"]) == ([], [])


def test_a_signal_published_after_the_view_was_first_read_shows_in_the_next_read(
    server: PageServer, telemetry: TelemetryLog
) -> None:
    before = len(_get(server, "?hours=1.06")[1]["sessions"])
    payload = {
        "resourceLogs": [
            {
                "resource": {"attributes": []},
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "attributes": [
                                    {"key": "event.name", "value": {"stringValue": "user_prompt"}},
                                    {"key": "session.id", "value": {"stringValue": "late"}},
                                    {"key": "event.sequence", "value": {"intValue": "0"}},
                                    {"key": "event.timestamp", "value": {"stringValue": "2026-10-09T22:00:00Z"}},
                                ]
                            }
                        ]
                    }
                ],
            }
        ]
    }

    telemetry.publish(signals(payload))

    assert len(_get(server, "?hours=1.06")[1]["sessions"]) == before + 1


def test_republishing_an_export_does_not_count_it_twice(server: PageServer, telemetry: TelemetryLog) -> None:
    before = _get(server, "?hours=1.06")[1]
    publish_recorded(telemetry)

    assert _get(server, "?hours=1.06")[1]["slices"] == before["slices"]


@pytest.mark.parametrize("query", ["?hours=0", "?hours=-1", "?hours=soon", "?hours=nan", "?hours=inf"])
def test_a_window_that_is_not_a_positive_number_is_refused(server: PageServer, query: str) -> None:
    status, body = _get(server, query)

    assert (status, "positive number" in body["error"]) == (400, True)


def test_an_instance_that_receives_no_telemetry_cannot_report_session_health(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES, keys=KEYS)) as server:
        status, body = _get(server)

    assert (status, "telemetry" in body["error"]) == (501, True)


def test_a_session_that_loaded_the_completion_skill_then_delivered_is_complete_by_the_servers_analytics(
    tmp_path: Path, telemetry: TelemetryLog
) -> None:
    def at(kind: str, offset: float, **fields: object) -> Signal:
        return Signal("claude-code", "done", kind, NOW - 3600 + offset, f"done:{kind}:{offset}", **fields)  # type: ignore[arg-type]

    telemetry.publish(
        [
            at("prompt", 0, branch="claude/task-8-x", turn="p1", detail="human"),
            at("request", 1, branch="claude/task-8-x", turn="p1", model="m", seconds=1),
            at("tool", 2, branch="claude/task-8-x", turn="p1", name="Edit", ok=True, seconds=0.5),
            at("skill", 3, branch="claude/task-8-x", turn="p1", name="completing-tasks"),
            at("deliver", 4, branch="claude/task-8-x", turn="p1"),
            at("reply", 5, branch="claude/task-8-x", turn="p1"),
        ]
    )
    declared = Analytics(completion_skill="completing-tasks")

    with serve(
        tmp_path, BoardFeed(roles=ROLES, machines=MACHINES, keys=KEYS), telemetry=telemetry, analytics=declared, clock=lambda: NOW
    ) as live:
        _, body = _get(live, "?hours=1")
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES, keys=KEYS), telemetry=telemetry, clock=lambda: NOW) as bare:
        _, undeclared = _get(bare, "?hours=1")

    (row,) = body["sessions"]
    assert (row["task"], row["complete"], row["steps_before_edit"], row["interrupts"]) == ("TASK-8", True, 1, 0)
    assert body["slices"][0]["complete"] is True
    assert undeclared["sessions"][0]["complete"] is False


def test_a_window_longer_than_the_telemetry_history_is_refused_with_the_history_s_and_a_shorter_one_is_answered(
    server: PageServer,
) -> None:
    status, refused = _get(server, "?hours=24")
    shorter_status, history = _get(server, "?hours=0.5")

    assert (status, 3000 < refused["history_s"] < 4 * 3600, "longer than the history" in refused["error"]) == (
        400,
        True,
        True,
    )
    assert (shorter_status, history["window_s"]) == (200, 1800)



def test_the_public_module_gives_the_rows_the_route_serves_for_the_same_exports(
    server: PageServer, telemetry: TelemetryLog
) -> None:
    """Over a window that is the whole telemetry history, so the route leaves out no record the exports carry."""
    history = NOW - min(s.time for s in telemetry.read())
    hours = history / 3600
    if hours * 3600 > history:  # a window one rounding longer than the history is refused
        hours = math.nextafter(hours, 0)
    status, body = _get(server, f"?hours={hours!r}")
    exports = [
        json.loads(line)
        for name in ("claude_code/otlp.ndjson", "codex/otlp.ndjson")
        for line in (FIXTURES / name).read_text().splitlines()
    ]

    rows = sessions.session_health(exports, KEYS)

    dumped = [row.model_dump(mode="json", by_alias=True, exclude_unset=True) for row in rows]
    sliced = [s.model_dump(mode="json", by_alias=True, exclude_unset=True) for s in sessions.slice_health(rows)]
    assert status == 200
    assert (dumped, sliced) == (body["sessions"], body["slices"])
