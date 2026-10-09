"""`serve` records every machine event and lane change into StarPulse's own store."""

import time
from pathlib import Path

import pytest
from sqlalchemy import text

from starpulse._internal.api import server
from starpulse._internal.eventlog import events
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import HistoryStore
from starpulse.tests import fake_board


def _rows(store: HistoryStore, table: str, columns: str) -> list[tuple]:
    with store.engine.connect() as db:
        return [tuple(row) for row in db.execute(text(f"SELECT {columns} FROM {table} ORDER BY id"))]


def _until(done) -> None:
    deadline = time.monotonic() + 10
    while not done():
        assert time.monotonic() < deadline, "serve never recorded it"
        time.sleep(0.01)


def test_serve_records_run_and_task_machine_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fake_board, "BUILT", [])
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    monkeypatch.setattr(server, "_STATIC", static)
    monkeypatch.setattr(server, "serve_until_stopped", lambda httpd, feed: None)
    config = tmp_path / "starpulse.toml"
    config.write_text('[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["open", "shut"]\n')

    server.main(["--config", str(config), "--port", "0"])

    own = HistoryStore(f"sqlite:///{tmp_path / 'starpulse-history.sqlite'}", {})
    log = EventLog(str(own.engine.url))
    log.append(events.STREAM, {"machine": "in-progress", "event": "WORKTREE_READY", "task": "FAKE-1", "time": 10.0})
    log.append(events.STREAM, {"machine": "authoring-skills", "event": "GUIDANCE_READ", "run": "run-1", "time": 11.0})
    _until(lambda: len(_rows(own, "starpulse_machine_events", "id")) == 2)

    assert _rows(own, "starpulse_machine_events", "task, run, machine, event") == [
        ("FAKE-1", None, "in-progress", "WORKTREE_READY"),
        (None, "run-1", "authoring-skills", "GUIDANCE_READ"),
    ]
    assert _rows(own, "starpulse_lane_changes", "task, old_status, new_status") == [("FAKE-1", None, "open")]
