"""`starpulse_signal_folds`: per-session folds under a basis, advanced from a persisted rowid cursor, read by window."""

import dataclasses
import json
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, text

from starpulse.contracts.signals import CLAUDE_CODE, Signal
from starpulse.event_log.event_log import EventLog, prune_forever
from starpulse.flow_metrics.model import cells, flow, session_health, steps
from starpulse.harness_telemetry.adapters.inbound.telemetry import KEEP_S
from starpulse.harness_telemetry.adapters.outbound.signal_table import SignalTable
from starpulse.views.adapters.outbound import signal_folds
from starpulse.views.adapters.outbound.signal_folds import CURSOR, SignalFolds, basis

from tests.unit.flow_metrics.test_folds import (
    ANALYTICS,
    KEYS,
    TASKS,
    WINDOW_START,
    finish,
    history,
    sig,
    whole_list,
    work,
)


def opened(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


def seed(log: EventLog, found: list[Signal]) -> None:
    SignalTable(log.engine).insert(asdict(s) for s in found)


def session_of(session: str, begin: float) -> list[Signal]:
    return [sig("request", begin + n, session, model="m", seconds=1.0) for n in range(2)]


def sessions_folded(log: EventLog) -> int:
    with log.engine.connect() as db:
        return db.execute(text("SELECT count(DISTINCT harness || session) FROM starpulse_signal_folds")).scalar() or 0


def captured(log: EventLog) -> list[tuple[str, Any]]:
    """Every statement the engine runs from now on, with its parameters."""
    seen: list[tuple[str, Any]] = []

    def record(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool) -> None:
        seen.append((statement, parameters))

    event.listen(log.engine, "before_cursor_execute", record)
    return seen


def test_a_restart_with_a_stored_cursor_reads_no_signal_at_or_below_it(tmp_path: Path) -> None:
    log = opened(tmp_path)
    seed(log, session_of("old1", 100.0) + session_of("old2", 200.0))
    SignalFolds(log, KEYS, ANALYTICS).catch_up()
    cursor = log.setting(CURSOR)
    assert cursor == 4

    restarted = SignalFolds(log, KEYS, ANALYTICS)
    seen = captured(log)
    assert restarted.catch_up() == 0
    on_signals = [(s, p) for s, p in seen if "starpulse_signals" in s]

    assert on_signals
    assert all("rowid >" in s and cursor in tuple(p) for s, p in on_signals)

    seed(log, session_of("new", 300.0))
    seen.clear()
    assert SignalFolds(log, KEYS, ANALYTICS).catch_up() == 1
    loaded = {tuple(p)[:2] for s, p in seen if "starpulse_signals" in s and "fields" in s.split("FROM")[0]}
    assert loaded == {(CLAUDE_CODE, "new")}


def test_a_fold_that_raises_leaves_the_cursor_before_that_session_and_passes_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = opened(tmp_path)
    seed(log, session_of("s1", 100.0) + session_of("s2", 200.0) + session_of("s3", 300.0))
    real = signal_folds.VIEWS["health"]

    def raising(group: list[Signal], keys: Any, analytics: Any) -> Any:
        if group[0].session == "s2":
            raise ValueError("seeded")
        return real(group, keys, analytics)

    monkeypatch.setitem(signal_folds.VIEWS, "health", raising)
    folds = SignalFolds(log, KEYS, ANALYTICS)

    assert folds.catch_up() == 2
    assert log.setting(CURSOR) == 2
    assert {row["session"] for row in session_health.combine_health(folds.window(0.0)["health"])} == {"s1", "s3"}
    assert sessions_folded(log) == 2

    monkeypatch.setitem(signal_folds.VIEWS, "health", real)

    assert folds.catch_up() == 1
    assert (log.setting(CURSOR), sessions_folded(log)) == (6, 3)
    assert folds.catch_up() == 0


def test_a_window_with_a_session_that_began_before_it_equals_the_whole_list_output(tmp_path: Path) -> None:
    log = opened(tmp_path)
    before = [s for s in work("long", 9, 1100.0, ["read"] * 30 + ["edit", "test"], skill=True) if s.time < WINDOW_START]
    before += [s for s in finish("long", 9, 2000.0) if s.time < WINDOW_START]
    assert before
    seed(log, before + history())
    folds = SignalFolds(log, KEYS, ANALYTICS)
    folds.catch_up()

    window = folds.window(WINDOW_START)
    got = {
        "session_health": session_health.combine_health(window["health"]),
        "session_steps": steps.combine_steps(window["steps"]),
        "transition_cost": cells.combine_cost(window["cost"], TASKS),
        "directly_follows": flow.combine_edges(window["runs"], TASKS, ANALYTICS),
    }

    expected = whole_list()
    assert got["session_health"]
    for view, rows in got.items():
        assert json.loads(json.dumps(rows)) == json.loads(json.dumps(expected[view])), view


def test_a_window_leaves_out_a_session_that_ended_before_it(tmp_path: Path) -> None:
    log = opened(tmp_path)
    seed(log, session_of("gone", 100.0) + session_of("kept", 5000.0))
    folds = SignalFolds(log, KEYS, ANALYTICS)
    folds.catch_up()

    sessions = {row["session"] for row in session_health.combine_health(folds.window(1000.0)["health"])}

    assert sessions == {"kept"}


def test_a_changed_basis_refolds_every_old_row_once(tmp_path: Path) -> None:
    log = opened(tmp_path)
    seed(log, session_of("s1", 100.0) + session_of("s2", 200.0) + session_of("s3", 300.0))
    old = SignalFolds(log, KEYS, ANALYTICS)
    assert old.catch_up() == 3
    assert old.catch_up() == 0

    other = dataclasses.replace(ANALYTICS, completion_skill="finishing")
    new = SignalFolds(log, KEYS, other)

    assert new.basis != old.basis
    assert new.catch_up() == 3
    assert new.catch_up() == 0
    assert SignalFolds(log, KEYS, other).catch_up() == 0
    with log.engine.connect() as db:
        assert set(db.execute(text("SELECT DISTINCT basis FROM starpulse_signal_folds")).scalars()) == {new.basis}


def test_the_basis_follows_the_task_keys_and_the_analytics_config() -> None:
    other_keys = dataclasses.replace(KEYS, key_format="ENG-{}")

    assert basis(KEYS, ANALYTICS) == basis(KEYS, dataclasses.replace(ANALYTICS))
    assert basis(KEYS, ANALYTICS) != basis(other_keys, ANALYTICS)
    assert basis(KEYS, ANALYTICS) != basis(KEYS, dataclasses.replace(ANALYTICS, roots=("/x",)))
    assert basis(KEYS, None) != basis(KEYS, ANALYTICS)


def test_the_prune_pass_deletes_fold_rows_older_than_the_keep_window(tmp_path: Path) -> None:
    log = opened(tmp_path)
    now = time.time()
    seed(log, session_of("stale", now - 2 * KEEP_S) + session_of("fresh", now - 10))
    SignalFolds(log, KEYS, ANALYTICS).catch_up()
    assert sessions_folded(log) == 2

    stop = threading.Event()
    stop.set()
    prune_forever(log, retention_days=30, archive_dir=tmp_path / "archive", stop=stop, signal_keep=KEEP_S)

    with log.engine.connect() as db:
        left = set(db.execute(text("SELECT DISTINCT session FROM starpulse_signal_folds")).scalars())
    assert left == {"fresh"}
