"""`starpulse_signals`: the signal store's idempotent insert, the Loki copy into it, and the hourly prune of its rows."""

import json
import threading
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import text

from starpulse.event_log.event_log import EventLog, prune_forever
from starpulse.event_log.tables import signals
from starpulse.harness_telemetry.adapters.inbound.telemetry import KEEP_S, TelemetryLog
from starpulse.harness_telemetry.adapters.outbound.loki import LokiSignals
from starpulse.harness_telemetry.adapters.outbound.signal_table import SignalTable
from starpulse.runtime.signal_copy import copy_signals

from tests.integration.harness_telemetry.test_loki_signals import FakeLoki, served, signal


def opened(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


def keys(log: EventLog) -> list[str]:
    with log.engine.connect() as db:
        return list(db.execute(text("SELECT key FROM starpulse_signals ORDER BY key")).scalars())


def test_an_export_replayed_adds_no_row(tmp_path: Path) -> None:
    log = opened(tmp_path)
    table = SignalTable(log.engine)
    export = [asdict(signal(n, 100.0 * n)) for n in (1, 2, 3)]

    first = table.insert(export)
    replayed = table.insert(export)
    overlapping = table.insert([*export, asdict(signal(4, 400.0)), asdict(signal(4, 400.0))])

    assert (first, replayed, overlapping, keys(log)) == (3, 0, 1, ["k1", "k2", "k3", "k4"])


def test_a_row_keeps_its_stored_fields_and_the_columns_a_read_filters_by(tmp_path: Path) -> None:
    log = opened(tmp_path)
    SignalTable(log.engine).insert([asdict(signal(1, 100.0))])

    with log.engine.connect() as db:
        row = db.execute(text("SELECT harness, session, time, kind, fields FROM starpulse_signals")).one()

    stored = json.loads(json.dumps(asdict(signal(1, 100.0))))
    assert (row.harness, row.session, row.time, row.kind, json.loads(row.fields)) == (
        signal(1, 100.0).harness,
        "s",
        100.0,
        "request",
        stored,
    )


def test_the_copy_inserts_the_window_once_and_a_rerun_inserts_none(tmp_path: Path) -> None:
    log = opened(tmp_path)
    table = SignalTable(log.engine)
    loki = FakeLoki()
    with served(loki) as url:
        source = LokiSignals(url)
        TelemetryLog(None, loki=source).publish([signal(1, 100.0), signal(2, 200.0), signal(3, 300.0), signal(4, 400.0)])
        table.insert([asdict(signal(3, 300.0))])  # already there, as after the adapters write both

        first = copy_signals(source, table, since=200.0)
        second = copy_signals(source, table, since=200.0)

    assert (first, second, keys(log)) == (2, 0, ["k2", "k3", "k4"])


def test_a_pass_of_the_prune_deletes_the_signals_older_than_the_keep_window(tmp_path: Path) -> None:
    log = opened(tmp_path)
    now = 10 * KEEP_S
    SignalTable(log.engine).insert(
        [asdict(signal(1, now - KEEP_S - 1)), asdict(signal(2, now - KEEP_S + 60)), asdict(signal(3, now))]
    )
    assert log.prune_signals(KEEP_S, now=now) == 1
    assert keys(log) == ["k2", "k3"]


def test_the_hourly_prune_loop_runs_the_signal_pass(tmp_path: Path) -> None:
    log = opened(tmp_path)
    SignalTable(log.engine).insert([asdict(signal(1, 1.0)), asdict(signal(2, 9e9))])
    stop = threading.Event()
    stop.set()  # one pass, then the loop returns

    prune_forever(log, retention_days=30, archive_dir=tmp_path / "archive", stop=stop, signal_keep=KEEP_S)

    assert keys(log) == ["k2"]


def test_the_two_reads_a_view_makes_each_use_their_index(tmp_path: Path) -> None:
    log = opened(tmp_path)
    with log.engine.begin() as db:
        for index in signals.indexes:  # seeded bare and indexed after: a bulk build, not 1M index insertions
            index.drop(db)
        db.execute(
            text(
                "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 1000000) "
                "INSERT INTO starpulse_signals (key, harness, session, time, kind, fields) "
                "SELECT 'k' || i, 'h' || (i % 3), 's' || (i % 5000), i * 0.5, 'request', '{}' FROM n"
            )
        )
        for index in signals.indexes:
            index.create(db)
        db.execute(text("ANALYZE"))
        window = db.execute(text("EXPLAIN QUERY PLAN SELECT key FROM starpulse_signals WHERE time >= 400000.0")).all()
        session = db.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT key FROM starpulse_signals "
                "WHERE harness = 'h1' AND session = 's7' AND time >= 100.0 ORDER BY time"
            )
        ).all()

    assert ("ix_starpulse_signals_time" in window[0].detail, "ix_starpulse_signals_session" in session[0].detail) == (True, True)
