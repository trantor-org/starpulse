"""`starpulse serve --hub` as an operator runs it: the config's Postgres database is migrated, the history consumer
writes a machine event there, and the server reads it back."""

import subprocess
import sys
import time
import urllib.error
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text

pytest.importorskip("alembic", reason="the hub extras are not installed")

from starpulse import events  # noqa: E402
from starpulse.event_log import EventLog  # noqa: E402
from starpulse.tests.integration.test_standalone import (  # noqa: E402, F401 - `build` is a fixture
    _free_port,
    _get,
    build,
)


def _until(check: Callable[[], object], proc: subprocess.Popen, what: str) -> object:
    deadline = time.monotonic() + 30
    while True:
        assert proc.poll() is None, f"the hub exited before {what}"
        try:
            if result := check():
                return result
        except OSError, urllib.error.URLError:
            pass
        assert time.monotonic() < deadline, f"never saw {what}"
        time.sleep(0.2)


@pytest.mark.usefixtures("build")
def test_a_hub_writes_a_machine_event_to_postgres_and_reads_it_back(pg_engine: Engine, tmp_path: Path) -> None:
    url = pg_engine.url.render_as_string(hide_password=False)
    with pg_engine.begin() as db:  # a database no earlier test migrated
        db.execute(text("DROP SCHEMA public CASCADE"))
        db.execute(text("CREATE SCHEMA public"))
    config = tmp_path / "starpulse.toml"
    config.write_text(f'database_url = "{url}"\n')
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "starpulse.server", "--hub", "--port", str(port), "--config", str(config)]
    )
    try:
        _until(lambda: _get(port, "/api/snapshot")[0] == 200, proc, "serving")
        events.publish("board", "MOVED", actor="tester", task="HUB-1", now=100.0, log=EventLog(url))

        path = _until(lambda: _get(port, "/api/history?task=HUB-1&flow=board")[1]["steps"], proc, "the event read back")
        assert path == 1
        with create_engine(url).connect() as db:
            row = db.execute(text("SELECT task, machine, event, actor FROM starpulse_machine_events")).one()
        assert tuple(row) == ("HUB-1", "board", "MOVED", "tester")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
