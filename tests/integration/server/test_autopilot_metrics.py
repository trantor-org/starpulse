"""`GET /metrics` carries the autopilot's switch, ledger and admission tally, read from the store it was seeded with."""

from __future__ import annotations

import urllib.request
from pathlib import Path

from starpulse.board.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog
from starpulse.runtime.adapter_kit import serve, url
from starpulse.scheduler.adapters.exposition import autopilot_exposition
from starpulse.scheduler.adapters.loop import TALLY_KEY
from starpulse.scheduler.model.toggle import KEY as SWITCH_KEY

from tests.machines import MACHINES, ROLES


def _metrics(server: object) -> str:
    with urllib.request.urlopen(url(server, "/metrics"), timeout=5) as resp:
        return resp.read().decode()


def test_metrics_carries_the_four_autopilot_series_of_the_seeded_store(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    log.set_setting(SWITCH_KEY, True, updated_at=1_700_000_000)
    log.set_setting(TALLY_KEY, {"admitted": 3, "refused": 1})

    with serve(
        tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), autopilot_metrics=lambda: autopilot_exposition(log)
    ) as server:
        body = _metrics(server)

    lines = body.splitlines()
    assert "starpulse_autopilot_enabled 1" in lines
    assert "starpulse_autopilot_switch_changed_timestamp_seconds 1700000000" in lines
    assert "starpulse_autopilot_ledger_runs 0" in lines
    assert 'starpulse_autopilot_decisions_total{verdict="admitted"} 3' in lines
    assert 'starpulse_autopilot_decisions_total{verdict="refused"} 1' in lines
