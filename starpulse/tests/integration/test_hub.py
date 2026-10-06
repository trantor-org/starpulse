"""`starpulse serve --hub` as an operator runs it: the config's Postgres database is migrated, the history consumer
writes a machine event there, and the server reads it back."""

import json
import subprocess
import sys
import time
import urllib.error
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text

pytest.importorskip("alembic", reason="the hub extras are not installed")

from starpulse import events  # noqa: E402
from starpulse.event_log import EventLog  # noqa: E402
from starpulse.tests.integration.test_standalone import (  # noqa: E402, F401 - `build` is a fixture
    _free_port,
    build,
)
from starpulse.tests.mock_issuer import call, session_of, sign_in  # noqa: E402


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
def test_a_hub_writes_a_machine_event_to_postgres_and_reads_it_back(
    pg_engine: Engine, issuer: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = pg_engine.url.render_as_string(hide_password=False)
    with pg_engine.begin() as db:  # a database no earlier test migrated
        db.execute(text("DROP SCHEMA public CASCADE"))
        db.execute(text("CREATE SCHEMA public"))
    config = tmp_path / "starpulse.toml"
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    config.write_text(
        f'database_url = "{url}"\n[oidc]\nissuer = "{issuer}"\nclient_id = "hub"\n'
        f'client_secret_env = "HUB_OIDC_SECRET"\nredirect_uri = "http://127.0.0.1:{port}/auth/callback"\n'
        'allowed_groups = ["ops"]\n'
    )
    monkeypatch.setenv("HUB_OIDC_SECRET", "hub-secret")
    proc = subprocess.Popen(
        [sys.executable, "-m", "starpulse.server", "--hub", "--port", str(port), "--config", str(config)]
    )
    try:
        _until(lambda: call(f"{base}/api/snapshot")[0] == 401, proc, "serving, and answering 401 before sign-in")
        cookie = {"Cookie": session_of(sign_in(base, issuer, "alice", ["ops"]))}
        assert call(f"{base}/api/snapshot", headers=cookie)[0] == 200
        events.publish("board", "MOVED", actor="tester", task="HUB-1", now=100.0, log=EventLog(url))

        def steps() -> object:
            answer = call(f"{base}/api/history?task=HUB-1&flow=board", headers=cookie)
            return json.loads(answer[2])["steps"]

        path = _until(steps, proc, "the event read back")
        assert path == 1
        with create_engine(url).connect() as db:
            row = db.execute(text("SELECT task, machine, event, actor FROM starpulse_machine_events")).one()
        assert tuple(row) == ("HUB-1", "board", "MOVED", "tester")
        tomorrow = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y%m%d")
        with create_engine(url).connect() as db:  # the hub made it before the clock reached it
            assert db.execute(text("SELECT to_regclass(:name)"), {"name": f"starpulse_events_{tomorrow}"}).scalar()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
