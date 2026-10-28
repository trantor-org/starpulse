"""GET /api/history?task=&hours=: every machine event of one task in a window, with each transition's from and to state."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.runtime.adapter_kit import serve, url
from starpulse.views.page_server import PageServer

from tests.machines import MACHINES, ROLES

NOW = 100 * 86400.0
HOUR = 3600.0
RETENTION_DAYS = 30


def _get(server: PageServer, query: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"/api/history{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _record(store: HistoryStore, n: int, task: str, machine: str, event: str, at: float) -> None:
    store.record_machine(f"e{n}-0", {"event_id": f"e{n}", "machine": machine, "event": event, "task": task, "time": at})


@pytest.fixture
def server(tmp_path: Path) -> Iterator[PageServer]:
    """PROJ-7's events on two machines interleaved with PROJ-8's, one PROJ-7 event older than 24h and one past retention, and PROJ-9 with only a past-retention event."""
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES, retention_days=RETENTION_DAYS)
    events = [
        ("PROJ-7", "in-progress", "WORKTREE_READY", NOW - 40 * 86400),
        ("PROJ-7", "in-progress", "WORKTREE_READY", NOW - 30 * HOUR),
        ("PROJ-7", "authoring-skills", "GUIDANCE_READ", NOW - 3 * HOUR),
        ("PROJ-8", "in-progress", "WORKTREE_READY", NOW - 2 * HOUR),
        ("PROJ-7", "in-progress", "RED_PROVEN", NOW - HOUR),
        ("PROJ-7", "authoring-skills", "SKILL_DRAFTED", NOW - 2 * HOUR),
        ("PROJ-9", "in-progress", "WORKTREE_READY", NOW - 40 * 86400),
    ]
    for n, event in enumerate(events):
        _record(store, n, *event)
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), history=store, clock=lambda: NOW) as server:
        yield server


def test_a_task_answers_every_machine_event_in_the_window_in_time_order_with_from_and_to(server: PageServer) -> None:
    assert _get(server, "?task=PROJ-7&hours=24") == (
        200,
        {
            "task": "PROJ-7",
            "hours": 24.0,
            "events": [
                {
                    "at": NOW - 3 * HOUR,
                    "machine": "authoring-skills",
                    "event": "GUIDANCE_READ",
                    "from": "guidance_pending",
                    "to": "guidance_read",
                },
                {
                    "at": NOW - 2 * HOUR,
                    "machine": "authoring-skills",
                    "event": "SKILL_DRAFTED",
                    "from": "guidance_read",
                    "to": "skill_drafted",
                },
                {
                    "at": NOW - HOUR,
                    "machine": "in-progress",
                    "event": "RED_PROVEN",
                    "from": "worktree_ready",
                    "to": "red_proven",
                },
            ],
        },
    )


def test_a_window_past_retention_answers_the_retained_events_only_and_one_wholly_past_it_answers_none(
    server: PageServer,
) -> None:
    status, wide = _get(server, "?task=PROJ-7&hours=100000")
    assert status == 200
    assert [e["at"] for e in wide["events"]][0] == NOW - 30 * HOUR
    assert _get(server, "?task=PROJ-9&hours=100000") == (200, {"task": "PROJ-9", "hours": 100000.0, "events": []})


@pytest.mark.parametrize("hours", ["0", "-1", "soon"])
def test_a_window_that_is_not_a_positive_number_of_hours_is_refused(server: PageServer, hours: str) -> None:
    assert _get(server, f"?task=PROJ-7&hours={hours}")[0] == 400
