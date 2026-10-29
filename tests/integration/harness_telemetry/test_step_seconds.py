"""Step timings as a Prometheus histogram: what the adapter observes and serves at `/metrics`."""

import re
import urllib.request
from http.server import ThreadingHTTPServer
from threading import Thread

from starpulse.harness_telemetry.adapters.inbound.claude_code import ClaudeCodeAdapter, handler
from starpulse.harness_telemetry.adapters.inbound.telemetry import CLAUDE_CODE, Signal
from starpulse.harness_telemetry.adapters.outbound import step_seconds


def count(kind: str) -> float:
    series = rf'^starpulse_step_seconds_count{{harness="{CLAUDE_CODE}",kind="{kind}"}} (\S+)$'
    match = re.search(series, step_seconds.exposition().decode(), re.MULTILINE)
    return float(match.group(1)) if match else 0.0


def test_the_seconds_of_a_request_tool_and_hook_are_observed_by_kind() -> None:
    kinds = ("request", "tool", "hook")
    before = {kind: count(kind) for kind in kinds}

    step_seconds.observe(Signal(CLAUDE_CODE, "s", kind, 1.0, f"k-{kind}", seconds=2.0) for kind in kinds)

    assert {kind: count(kind) - before[kind] for kind in kinds} == dict.fromkeys(kinds, 1)


def test_a_signal_with_no_duration_or_another_kind_is_not_observed() -> None:
    before = step_seconds.exposition()

    step_seconds.observe(
        [Signal(CLAUDE_CODE, "s", "request", 1.0, "k1"), Signal(CLAUDE_CODE, "s", "prompt", 1.0, "k2", seconds=3.0)]
    )

    assert step_seconds.exposition() == before


def test_the_adapter_serves_the_histogram_at_metrics() -> None:
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        handler(
            ClaudeCodeAdapter(None), lambda event: None, None, (step_seconds.CONTENT_TYPE, step_seconds.exposition)
        ),
    )
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        step_seconds.observe([Signal(CLAUDE_CODE, "s", "tool", 1.0, "k3", seconds=1.5)])
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/metrics") as response:
            body = response.read().decode()
            content_type = response.headers["Content-Type"]
    finally:
        server.shutdown()
        server.server_close()

    assert content_type.startswith("text/plain")
    assert "# TYPE starpulse_step_seconds histogram" in body
