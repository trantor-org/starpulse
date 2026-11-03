"""The Claude Code adapter as a `contexts` thread: `[claude_code]` makes `serve` receive OTLP exports and append the events
they map to, and stopping the process closes the listener."""

import dataclasses
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from starpulse.event_log.event_log import EventLog, Tail
from starpulse.harness_telemetry.model.claude_code_config import ClaudeCode
from starpulse.runtime.config import load
from starpulse.runtime.contexts import default_starters

from tests.unit.harness_telemetry.test_claude_code import exports

WAIT_S = 5.0


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _post(port: int, payload: dict) -> int:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/logs",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=WAIT_S) as response:
        return response.status


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def test_the_context_appends_each_export_to_the_event_log_and_closes_its_port_when_stopped(tmp_path: Path) -> None:
    port = _free_port()
    config = dataclasses.replace(load(None), claude_code=ClaudeCode(port=port))
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    stop = threading.Event()
    start = default_starters(config, None, tmp_path, log, ["claude-code"], stop)["claude-code"]

    start(stop)
    try:
        assert [_post(port, payload) for payload in exports("feature/task-7-x")[:2]] == [200, 200]
        events = Tail.replay(log, "machine:events").poll()
        assert {(e.fields["event"], e.fields["task"]) for e in events} >= {("SESSION_STARTED", "TASK-7")}
    finally:
        stop.set()

    deadline = time.monotonic() + WAIT_S
    while _listening(port) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _listening(port)
