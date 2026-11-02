"""`GET /metrics` carries the autopilot's switch, ledger and admission tally, read from the store it was seeded with."""

from __future__ import annotations

import urllib.request
from pathlib import Path

from starpulse.board.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog
from starpulse.runtime.adapter_kit import serve, url
from starpulse.scheduler.adapters.exposition import autopilot_exposition
from starpulse.scheduler.adapters.loop import GATE_TALLY_KEY, TALLY_KEY
from starpulse.scheduler.model.toggle import KEY as SWITCH_KEY

from tests.machines import MACHINES, ROLES


def _metrics(server: object) -> str:
    with urllib.request.urlopen(url(server, "/metrics"), timeout=5) as resp:
        return resp.read().decode()


def test_metrics_carries_the_four_autopilot_series_of_the_seeded_store(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    log.set_setting(SWITCH_KEY, True, updated_at=1_700_000_000)
    log.put_state(TALLY_KEY, {"admitted": 3, "refused": 1})

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


def test_metrics_carries_a_zero_series_for_every_gate_and_verdict_so_a_quiet_hour_is_data(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    log.put_state(GATE_TALLY_KEY, {"memory/refused": 4, "cpu/admitted": 9})

    lines = autopilot_exposition(log).splitlines()

    assert 'starpulse_autopilot_gate_decisions_total{gate="memory",verdict="refused"} 4' in lines
    assert 'starpulse_autopilot_gate_decisions_total{gate="cpu",verdict="admitted"} 9' in lines
    assert 'starpulse_autopilot_gate_decisions_total{gate="review",verdict="refused"} 0' in lines
    assert 'starpulse_autopilot_gate_decisions_total{gate="profile",verdict="admitted"} 0' in lines
    assert len([line for line in lines if line.startswith("starpulse_autopilot_gate_decisions_total{")]) == 10
