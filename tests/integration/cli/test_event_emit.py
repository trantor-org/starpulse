"""`starpulse event emit` posts one CloudEvent to a server's ingest, signed as the producer named by `--source`."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from starpulse.__main__ import main


class _Ingest(BaseHTTPRequestHandler):
    seen: list[dict[str, Any]] = []
    answer = 201

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.seen.append(
            {
                "path": self.path,
                "type": self.headers["Content-Type"],
                "auth": self.headers["Authorization"],
                "event": json.loads(body),
            }
        )
        self.send_response(self.answer)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"accepted": true}')

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def ingest() -> Any:
    _Ingest.seen, _Ingest.answer = [], 201
    server = HTTPServer(("127.0.0.1", 0), _Ingest)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_a_step_event_posts_as_a_cloudevent_under_the_producers_token(
    ingest: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STARPULSE_PRODUCER_DAGU_TOKEN", "secret")

    code = main(
        ["event", "emit", "--url", ingest, "--source", "dagu", "--type", "StepFinished", "--subject", "run-1"]
        + ["--data", "workflow=nightly", "--data", "status=partially_succeeded"]
    )

    assert code == 0
    [seen] = _Ingest.seen
    assert (seen["path"], seen["type"], seen["auth"]) == (
        "/api/machine-events",
        "application/cloudevents+json",
        "Bearer secret",
    )
    assert seen["event"] | {"id": "x", "time": "t"} == {
        "specversion": "1.0",
        "id": "x",
        "time": "t",
        "source": "dagu",
        "type": "StepFinished",
        "subject": "run-1",
        "data": {"workflow": "nightly", "status": "partially_succeeded"},
    }


def test_the_url_comes_from_the_write_url_variable_and_a_refusal_exits_one(
    ingest: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("STARPULSE_WRITE_URL", ingest)
    monkeypatch.setenv("STARPULSE_PRODUCER_CI_BOT_TOKEN", "t")
    _Ingest.answer = 403

    code = main(["event", "emit", "--source", "ci-bot", "--type", "X", "--machine", "m", "--actor", "a", "--run", "r"])

    assert code == 1
    assert "403" in capsys.readouterr().err
    assert _Ingest.seen[0]["event"]["machine"] == "m"


def test_a_missing_token_variable_is_named_on_stderr(
    ingest: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("STARPULSE_PRODUCER_DAGU_TOKEN", raising=False)

    code = main(["event", "emit", "--url", ingest, "--source", "dagu", "--type", "StepStarted", "--subject", "r"])

    assert code == 1
    assert "STARPULSE_PRODUCER_DAGU_TOKEN" in capsys.readouterr().err
    assert _Ingest.seen == []
