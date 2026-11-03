"""`GET /autopilot-log` serves the decision log the scheduler kept in the store, so a gauge reads StarPulse."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

from starpulse.board.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog
from starpulse.runtime.adapter_kit import serve, url
from starpulse.scheduler.adapters.exposition import autopilot_log
from starpulse.scheduler.model.decision_log import KEY

from tests.machines import MACHINES, ROLES


def _served(tmp_path: Path, log: EventLog) -> dict[str, Any]:
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), autopilot_log=lambda: autopilot_log(log)) as server:
        with urllib.request.urlopen(url(server, "/autopilot-log"), timeout=5) as resp:
            assert resp.headers["content-type"].startswith("application/json")
            return json.loads(resp.read())


def test_the_log_serves_the_days_starts_and_restore_of_the_seeded_store(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    kept = {
        "days": {"2026-11-02": {"admitted": 2, "refused/cpu": 1}},
        "starts": [{"task": "TASK-1", "at": 1_700_000_000.0}],
        "restored_at": 1_699_999_000.0,
    }
    log.put_state(KEY, kept)

    assert _served(tmp_path, log) == kept


def test_a_store_that_kept_nothing_serves_an_empty_log(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")

    assert _served(tmp_path, log) == {"days": {}, "starts": [], "restored_at": None}
