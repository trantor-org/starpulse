"""`starpulse backfill-telemetry`: the event log's `telemetry:signals` rows copied into Loki, each key once."""

import json
from dataclasses import asdict
from pathlib import Path

from starpulse.contracts.signals import Signal
from starpulse.event_log.event_log import EventLog
from starpulse.harness_telemetry.adapters.inbound.telemetry import TelemetryLog
from starpulse.harness_telemetry.adapters.outbound.loki import LokiSignals
from starpulse.runtime.telemetry_backfill import backfill

from tests.integration.harness_telemetry.test_loki_signals import FakeLoki, push, served, signal


def stream(log: EventLog, found: list[Signal]) -> None:
    """Seed the private stream as the adapters wrote it before the cutover."""
    for one in found:
        log.publish(TelemetryLog.STREAM, asdict(one), event_id=one.key)


def loki_keys(loki: FakeLoki) -> list[str]:
    return sorted(json.loads(text)["key"] for _, text in loki.lines)


def test_the_window_of_the_event_log_lands_in_loki_once_and_a_rerun_adds_none(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    stream(log, [signal(1, 100.0), signal(2, 200.0), signal(3, 300.0), signal(4, 400.0)])
    loki = FakeLoki()
    with served(loki) as url:
        target = LokiSignals(url)
        push(target, [signal(3, 300.0)])  # already there, as after the cutover

        first = backfill(log, target, since=200.0)
        second = backfill(log, target, since=200.0)

    assert (first, second, loki_keys(loki)) == (2, 0, ["k2", "k3", "k4"])


def test_a_push_the_rate_limit_refuses_is_retried_until_loki_takes_it(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    stream(log, [signal(1, 100.0), signal(2, 200.0)])
    loki = FakeLoki()
    loki.limited = 2
    with served(loki) as url:
        pushed = backfill(log, LokiSignals(url), since=0.0, pause=0.0)

    assert (pushed, loki_keys(loki)) == (2, ["k1", "k2"])
