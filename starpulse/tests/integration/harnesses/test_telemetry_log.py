"""The telemetry log over a real event log: what a replay, an outage, a window and a trim do to what is read."""

from dataclasses import asdict
from pathlib import Path

from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.harnesses.telemetry import CLAUDE_CODE, Signal, TelemetryLog


def signal(n: int, at: float) -> Signal:
    return Signal(CLAUDE_CODE, "s", "request", at, f"k{n}", model="m", input=n)


def log_at(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


def test_what_is_published_reads_back_equal_and_in_order(tmp_path: Path) -> None:
    telemetry = TelemetryLog(log_at(tmp_path))
    found = [signal(1, 100.0), signal(2, 50.0), signal(3, 200.0)]

    telemetry.publish(found)

    assert telemetry.read() == found


def test_a_replayed_signal_is_not_added_twice(tmp_path: Path) -> None:
    telemetry = TelemetryLog(log_at(tmp_path))

    telemetry.publish([signal(1, 100.0)])
    telemetry.publish([signal(1, 100.0), signal(2, 101.0)])

    assert [s.key for s in telemetry.read()] == ["k1", "k2"]


def test_a_second_reader_of_the_same_database_sees_what_the_first_published(tmp_path: Path) -> None:
    TelemetryLog(log_at(tmp_path)).publish([signal(1, 100.0)])

    assert [s.key for s in TelemetryLog(log_at(tmp_path)).read()] == ["k1"]


def test_a_read_returns_only_the_signals_from_the_window_on_and_a_later_publish_joins_them(tmp_path: Path) -> None:
    telemetry = TelemetryLog(log_at(tmp_path))
    telemetry.publish([signal(1, 100.0), signal(2, 200.0)])
    assert [s.key for s in telemetry.read(150.0)] == ["k2"]

    telemetry.publish([signal(3, 300.0)])

    assert [s.key for s in telemetry.read(150.0)] == ["k2", "k3"]


def test_signals_older_than_the_hold_before_the_newest_are_dropped(tmp_path: Path) -> None:
    telemetry = TelemetryLog(log_at(tmp_path), keep=100.0)

    telemetry.publish([signal(1, 100.0), signal(2, 250.0), signal(3, 300.0)])

    assert [s.key for s in telemetry.read()] == ["k2", "k3"]


def test_publishing_to_a_database_that_cannot_be_opened_drops_the_signals_without_raising(tmp_path: Path) -> None:
    telemetry = TelemetryLog(EventLog(f"sqlite:///{tmp_path / 'missing' / 'events.sqlite'}"))

    telemetry.publish([signal(1, 100.0)])  # must not raise: the export that carried it is still answered


def test_a_signal_a_newer_producer_wrote_with_a_field_this_version_lacks_is_still_read(tmp_path: Path) -> None:
    log = log_at(tmp_path)
    log.append(TelemetryLog.STREAM, {**asdict(signal(1, 100.0)), "from_the_future": 1}, event_id="k1")

    assert [s.key for s in TelemetryLog(log).read()] == ["k1"]


def test_a_codex_signal_stored_before_the_uncaptured_mark_existed_reads_as_uncaptured(tmp_path: Path) -> None:
    log = log_at(tmp_path)
    old = {k: v for k, v in asdict(signal(1, 100.0)).items() if k not in {"captured", "agent"}}
    log.append(TelemetryLog.STREAM, {**old, "harness": "codex"}, event_id="k1")

    (read,) = TelemetryLog(log).read()

    assert read.captured is False
