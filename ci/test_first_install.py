"""A first install end to end: `init`, `serve`, a stubbed Claude Code harness posting OTLP, a Task create and claim.

The stub is the harness's export and nothing else: it reads the `env` block `init` wrote to `.claude/settings.json` and
POSTs a recorded Claude Code log export to its `OTEL_EXPORTER_OTLP_ENDPOINT`, on the branch of the claimed Task. The
Task must then name the session that claimed it, and the same session must show in the analytics with that Task.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest
from tests.page_stub import held

import starpulse

SESSION = "11111111-1111-4111-8111-111111111111"
BRANCH = "claude/task-1-first-install"
DEADLINE = 60.0

# Nightly: ~10 s wall and ~11 CPU-s warm, almost all of it interpreter start-up and imports, one per process a first
# install runs: `init` 0.6, `migrate` 1.8, `task create` 0.6, `task claim` 0.65, the receiver 1.1 and `serve` with its
# `machine_sync` and API worker ~5. `migrate` is a step of the install (opening a store runs no maintenance) and each
# process is what the test proves works together, so none can be merged or run in-process. A first install changes
# rarely, so the nightly suite runs it and no pull request does.
pytestmark = pytest.mark.nightly


@pytest.fixture
def page_build():
    """`serve` refuses to start without a page build, which the test job does not make; the shared stub stands in for it."""
    with held(Path(starpulse.__file__).parent / "static"):
        yield


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _starpulse(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "starpulse", *args], cwd=cwd, env=env, capture_output=True, text=True)


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read())


def _until(probe, what: str, process: subprocess.Popen | None = None, log: Path | None = None):
    """The first truthy `probe()` within the deadline; a probe that raises OSError or HTTPError has not answered yet.

    A `process` that exits first fails at once with its `log`, rather than after the deadline.
    """
    end = time.monotonic() + DEADLINE
    while time.monotonic() < end:
        if process is not None and process.poll() is not None:
            pytest.fail(f"{what}: process exited {process.returncode}\n{log.read_text() if log else ''}")
        try:
            if found := probe():
                return found
        except OSError, urllib.error.HTTPError:
            pass
        time.sleep(0.3)
    pytest.fail(f"{what} did not happen within {DEADLINE:.0f}s")


def _export(ago_s: float) -> dict:
    """One recorded Claude Code user-prompt log export from `ago_s` seconds back, with this test's session and branch."""
    stamp = datetime.fromtimestamp(time.time() - ago_s, timezone.utc).isoformat()
    record = {
        "body": {"stringValue": "claude_code.user_prompt"},
        "timeUnixNano": str(time.time_ns()),
        "attributes": [
            {"key": "event.timestamp", "value": {"stringValue": stamp}},
            {"key": "event.sequence", "value": {"stringValue": str(int(ago_s))}},
            {"key": "vcs.ref.head.name", "value": {"stringValue": BRANCH}},
            {"key": "session.id", "value": {"stringValue": SESSION}},
            {"key": "event.name", "value": {"stringValue": "user_prompt"}},
            {"key": "prompt_length", "value": {"stringValue": "12"}},
        ],
    }
    resource = [{"key": "vcs.ref.head.name", "value": {"stringValue": BRANCH}}]
    scope = {"scope": {"name": "com.anthropic.claude_code.events"}, "logRecords": [record]}
    return {"resourceLogs": [{"resource": {"attributes": resource}, "scopeLogs": [scope]}]}


def _stub_harness(install: Path, receiver_port: int, ago_s: float) -> None:
    """Export as Claude Code does with the install's settings; only the port moves, as the README says it may."""
    env = json.loads((install / ".claude" / "settings.json").read_text())["env"]
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    assert env["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/json"
    endpoint = env["OTEL_EXPORTER_OTLP_ENDPOINT"].replace(":4318", f":{receiver_port}")
    request = urllib.request.Request(
        f"{endpoint}/v1/logs",
        data=json.dumps(_export(ago_s)).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as resp:
        assert resp.status == 200


def test_a_first_install_links_the_session_that_claims_a_task_to_it(tmp_path: Path, page_build: None) -> None:
    install = tmp_path / "demo"
    package_root = str(
        Path(starpulse.__file__).parent.parent
    )  # the subprocesses run the code under test, not an installed copy
    env = {
        **os.environ,
        "STARPULSE_TOKEN": "first-install-token",
        "STARPULSE_SESSION": SESSION,
        "PYTHONPATH": package_root,
    }
    env.pop("STARPULSE_CONFIG", None)
    init = _starpulse("init", "--dir", str(install), "--harness", "claude-code", cwd=tmp_path, env=env)
    assert init.returncode == 0, init.stderr
    migrate = _starpulse("migrate", cwd=install, env=env)
    assert migrate.returncode == 0, migrate.stderr

    port, receiver_port = _free_port(), _free_port()
    server = f"http://127.0.0.1:{port}"
    serve = subprocess.Popen(
        [sys.executable, "-m", "starpulse", "serve", "--port", str(port)],
        cwd=install,
        env=env,
        stderr=(tmp_path / "serve.log").open("w"),
    )
    receiver = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "starpulse.runtime.claude_code",
            "--config",
            "starpulse.toml",
            "--port",
            str(receiver_port),
        ],
        cwd=install,
        env=env,
        stderr=(tmp_path / "receiver.log").open("w"),
    )
    try:
        _until(lambda: _get(f"{server}/api/snapshot"), "serve answering", serve, tmp_path / "serve.log")

        created = _starpulse("task", "create", "First install", "--server", server, cwd=install, env=env)
        assert created.returncode == 0, created.stdout + created.stderr
        task = json.loads(created.stdout)["task"]
        # The server reads the board on a refresh, so a task just created is not claimable for a moment.
        # Poll over HTTP: each failed `claim` attempt would start a fresh interpreter.
        _until(lambda: _get(f"{server}/api/task/{task}"), "the task on the board")
        claimed = _starpulse("task", "claim", task, "--server", server, cwd=install, env=env)
        assert claimed.returncode == 0, claimed.stdout + claimed.stderr

        # The analytics refuse a window past their history, which begins at the oldest signal: one export is older.
        for ago_s in (600, 0):
            _until(lambda: _stub_harness(install, receiver_port, ago_s) or True, "the receiver accepting the export")

        def linked() -> bool:
            rows = _get(f"{server}/api/analytics/sessions?hours=0.05")["sessions"]
            return any(row["session"] == SESSION and str(row["task"]).lower() == task.lower() for row in rows)

        _until(linked, "the session appearing on the Task")
        assert f"**Assignee:** {SESSION}" in _get(f"{server}/api/task/{task}")["record"]["notes"]
    finally:
        for process in (receiver, serve):
            process.terminate()
        for process in (receiver, serve):
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
