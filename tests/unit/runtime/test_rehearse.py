"""`rehearse` exits clean only when the `serve` it starts on a copy of a store answers `/api/ready` 200 within its
budget, and says what was not ready otherwise; the config it starts `serve` from drops every outbound key."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from starpulse.runtime import rehearse as rehearsal
from starpulse.runtime.config import REHEARSE_ENV, load, rehearsal as reshape

# A stand-in for `serve`: answers /api/ready with the status and body in argv[3], then argv[4]'s later ones.
FAKE_SERVE = """
import http.server, json, sys
status, body = int(sys.argv[2]), sys.argv[3]
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(status)
        self.end_headers()
        self.wfile.write(body.encode())
    def log_message(self, *args):
        pass
http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
"""

READY = json.dumps({"ready": True, "components": {}})
UNREADY = json.dumps(
    {"ready": False, "components": {"contexts": {"ready": False, "detail": "not started: pulls"}}}
)


def fake(tmp_path: Path, status: int, body: str):
    script = tmp_path / "fake_serve.py"
    script.write_text(FAKE_SERVE)
    return lambda config, port: [sys.executable, str(script), str(port), str(status), body]


def passes(config: Path) -> list[str]:
    return [sys.executable, "-c", "pass"]


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text("")
    return path


def test_a_server_that_answers_ready_is_rehearsed_clean(tmp_path: Path, config: Path) -> None:
    failed = rehearsal.rehearse(config, "copy.sqlite", 20, serve=fake(tmp_path, 200, READY), migrate=passes, poll_s=0.05)

    assert failed is None


def test_a_server_that_stays_unready_fails_naming_the_component_within_the_budget(tmp_path: Path, config: Path) -> None:
    failed = rehearsal.rehearse(
        config, "copy.sqlite", 1.5, serve=fake(tmp_path, 503, UNREADY), migrate=passes, poll_s=0.05
    )

    assert failed is not None
    assert "contexts: not started: pulls" in failed


def test_a_server_that_exits_before_it_is_ready_fails_with_its_exit_code(config: Path) -> None:
    def exits(config: Path, port: int) -> list[str]:
        return [sys.executable, "-c", "import sys; print('Board lanes differ'); sys.exit(3)"]

    failed = rehearsal.rehearse(config, "copy.sqlite", 20, serve=exits, migrate=passes, poll_s=0.05)

    assert failed is not None
    assert "serve exited 3" in failed
    assert "Board lanes differ" in failed


def test_a_failed_migration_fails_without_starting_serve(config: Path) -> None:
    def refuses(config: Path) -> list[str]:
        return [sys.executable, "-c", "import sys; sys.exit(2)"]

    def never(config: Path, port: int) -> list[str]:
        raise AssertionError("serve started after a failed migrate")

    failed = rehearsal.rehearse(config, "copy.sqlite", 20, serve=never, migrate=refuses)

    assert failed is not None
    assert "migrate exited 2" in failed


def test_the_command_exits_0_when_ready_and_1_when_not(
    tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(rehearsal, "serve_command", fake(tmp_path, 200, READY))
    monkeypatch.setattr(rehearsal, "migrate_command", passes)
    monkeypatch.setattr(rehearsal, "POLL_S", 0.05)
    ready = rehearsal.main(["--config", str(config), "--database-url", "copy.sqlite", "--budget", "20"])
    monkeypatch.setattr(rehearsal, "serve_command", fake(tmp_path, 503, UNREADY))
    unready = rehearsal.main(["--config", str(config), "--database-url", "copy.sqlite", "--budget", "1"])

    assert (ready, unready) == (0, 1)
    assert "not started: pulls" in capsys.readouterr().err


def test_a_plain_path_names_a_sqlite_file() -> None:
    assert rehearsal.store_url("/data/copy.sqlite") == "sqlite:////data/copy.sqlite"
    assert rehearsal.store_url("postgresql://db/starpulse") == "postgresql://db/starpulse"


FULL = """
database_url = "sqlite:////srv/live.sqlite"
event_log_archive_dir = "/srv/live-archive"
tls_cert = "cert.pem"
tls_key = "key.pem"
session_start_url = "http://agents.example/start"
telemetry_loki_url = "http://loki.example"
pull_requests = true

[[runs]]
name = "ci"
type = "dagu"
url = "http://dagu.example"

[[repos]]
path = "child"
name = "child"
applied_by = "pin-bump"
"""


def test_a_rehearsal_loads_the_config_on_the_copy_with_every_outbound_key_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "starpulse.toml"
    path.write_text(FULL)
    spec = {"database_url": "sqlite:////tmp/copy.sqlite", "archive_dir": "/tmp/scratch/archive"}
    monkeypatch.setenv(REHEARSE_ENV, json.dumps(spec))

    config = load(path)

    assert config.database_url == "sqlite:////tmp/copy.sqlite"
    assert config.event_log_archive_dir == "/tmp/scratch/archive"
    assert config.tls is None
    assert config.session_start_url is None
    assert config.telemetry_loki_url is None
    assert len(config.runs) == 1  # Board assembly checks its writers against them; no context polls them
    assert len(config.repos) == 1
    assert config.pull_requests is False


def test_a_config_loads_as_written_without_a_rehearsal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "starpulse.toml"
    path.write_text(FULL)
    monkeypatch.delenv(REHEARSE_ENV, raising=False)

    config = load(path)

    assert config.database_url == "sqlite:////srv/live.sqlite"
    assert config.session_start_url == "http://agents.example/start"
    assert len(config.runs) == 1


def test_a_reshaped_config_keeps_what_the_rehearsal_does_not_drop() -> None:
    raw = {"hours": 3, "tls_cert": "c", "runs": [{"name": "x"}], "producers": [{"name": "p"}]}

    out = reshape(raw, {"database_url": "u", "archive_dir": "a"})

    assert out["hours"] == 3
    assert out["runs"] == raw["runs"]
    assert "tls_cert" not in out and "producers" not in out


def test_a_rehearsal_runs_only_the_contexts_that_reach_nothing_outside_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from starpulse.runtime.contexts import REHEARSED_CONTEXTS, contexts_of

    path = tmp_path / "starpulse.toml"
    path.write_text(FULL)
    monkeypatch.delenv(REHEARSE_ENV, raising=False)
    live = contexts_of(load(path))
    monkeypatch.setenv(REHEARSE_ENV, json.dumps({"database_url": "sqlite://", "archive_dir": "a"}))

    rehearsed = contexts_of(load(path))

    assert {"pulls", "scheduler", "runs", "sweeper"} <= set(live)
    assert rehearsed == list(REHEARSED_CONTEXTS) == ["flow-metrics", "board"]
