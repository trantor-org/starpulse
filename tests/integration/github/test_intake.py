"""The GitHub intake listener: a signed delivery is saved to `github_inbox` before it is answered, and nothing else is."""

import contextlib
import hashlib
import hmac
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from starpulse.github.adapters.inbound import listener
from starpulse.github.adapters.inbound.listener import bind
from starpulse.github.adapters.outbound.inbox import SqlInbox, github_inbox
from starpulse.github.model.github_config import GitHub

SECRET = b"intake-secret"
MAX_BODY = 2048
BODY = json.dumps({"action": "closed", "repository": {"full_name": "acme/widgets"}}).encode()


class Intake:
    def __init__(self, server: ThreadingHTTPServer, inbox: SqlInbox) -> None:
        self.server = server
        self.inbox = inbox

    def post(self, body: bytes = BODY, *, event: str = "pull_request", delivery: str = "d-1", signature: str | None = "") -> int:
        headers = {"X-GitHub-Event": event, "X-GitHub-Delivery": delivery, "Content-Type": "application/json"}
        if signature is not None:
            headers["X-Hub-Signature-256"] = signature or sign(body)
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}/", data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def raw(self, request: bytes) -> int:
        """The status of the answer to `request` sent as is; a request cut short is answered when the server's read times out."""
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=5) as connection:
            connection.sendall(request)
            return int(connection.recv(4096).split()[1])

    def get(self, path: str) -> str:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.server.server_port}{path}", timeout=5) as response:
            return response.read().decode()

    def rows(self) -> list:
        with self.inbox.engine.connect() as db:
            return list(db.execute(select(github_inbox)))


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()


@pytest.fixture
def intake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Intake]:
    monkeypatch.setattr(listener, "READ_TIMEOUT", 0.2)
    settings = GitHub(secret_env="X", organisation="acme", max_body_bytes=MAX_BODY, port=0)
    inbox = SqlInbox(f"sqlite:///{tmp_path / 'github.sqlite'}")
    server = bind(settings, SECRET, inbox)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    yield Intake(server, inbox)
    server.shutdown()
    server.server_close()


def test_a_signed_delivery_is_saved_with_its_raw_body_and_a_repeat_adds_no_row(intake: Intake) -> None:
    assert intake.post() == 202
    (row,) = intake.rows()
    assert (row.delivery_id, row.source, row.event, row.action, row.repository, bytes(row.body)) == (
        "d-1", "webhook", "pull_request", "closed", "acme/widgets", BODY,
    )  # fmt: skip

    assert intake.post() == 202
    assert len(intake.rows()) == 1


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"signature": None}, 401),
        ({"signature": "sha256=" + "0" * 64}, 401),
        ({"event": "gollum"}, 204),
        ({"body": json.dumps({"repository": {"full_name": "other/widgets"}}).encode()}, 204),
        ({"body": b"x" * (MAX_BODY + 1)}, 413),
    ],
)
def test_a_refused_delivery_gets_its_status_and_writes_no_row(intake: Intake, kwargs: dict, status: int) -> None:
    assert intake.post(**kwargs) == status
    assert intake.rows() == []


def test_a_commit_that_fails_answers_503_and_writes_no_row(intake: Intake, caplog: pytest.LogCaptureFixture) -> None:
    with intake.inbox.engine.begin() as db:
        db.execute(text("CREATE TRIGGER refuse BEFORE INSERT ON github_inbox BEGIN SELECT RAISE(ABORT, 'disk full'); END"))

    assert intake.post() == 503
    assert intake.rows() == []
    assert "disk full" in caplog.text
    assert "acme/widgets" not in caplog.text  # the INSERT's parameters hold the raw body


def test_each_verdict_is_counted_at_metrics(intake: Intake) -> None:
    intake.post()
    intake.post()
    intake.post(signature=None)
    metrics = intake.get("/metrics")
    assert 'starpulse_github_deliveries_total{event="pull_request",verdict="accepted"} 1.0' in metrics
    assert 'starpulse_github_deliveries_total{event="pull_request",verdict="duplicate"} 1.0' in metrics
    assert 'starpulse_github_deliveries_total{event="unverified",verdict="bad_signature"} 1.0' in metrics


def test_the_inbox_is_one_row_per_delivery_id_in_the_database(intake: Intake) -> None:
    intake.post(delivery="a")
    intake.post(delivery="b")
    with intake.inbox.engine.connect() as db:
        assert db.execute(select(func.count()).select_from(github_inbox)).scalar() == 2


@pytest.mark.parametrize(
    "request_line",
    [
        b"POST / HTTP/1.1\r\nX-GitHub-Delivery: x\r\n\r\n",
        b"POST / HTTP/1.1\r\nContent-Length: nine\r\n\r\n",
        "POST / HTTP/1.1\r\nContent-Length: \u00b2\r\n\r\n".encode(),
    ],
)
def test_a_missing_or_malformed_content_length_is_400_and_counted_invalid(intake: Intake, request_line: bytes) -> None:
    assert intake.raw(request_line) == 400
    assert 'verdict="invalid"} 1.0' in intake.get("/metrics")
    assert intake.rows() == []


def test_a_content_length_of_thousands_of_digits_is_413_not_a_crash(intake: Intake) -> None:
    assert intake.raw(b"POST / HTTP/1.1\r\nContent-Length: " + b"9" * 5000 + b"\r\n\r\n") == 413


def test_a_body_dripped_in_slower_than_the_read_deadline_is_dropped_with_408(intake: Intake) -> None:
    with socket.create_connection(("127.0.0.1", intake.server.server_port), timeout=5) as connection:
        connection.sendall(b"POST / HTTP/1.1\r\nContent-Length: 100\r\n\r\n")
        with contextlib.suppress(OSError):  # the server hangs up once the deadline passes
            for _ in range(6):
                time.sleep(0.1)  # each gap is under READ_TIMEOUT (0.2), the sum is not
                connection.sendall(b"x")
        assert int(connection.recv(4096).split()[1]) == 408


def test_a_body_that_stops_arriving_is_dropped_with_408(intake: Intake) -> None:
    assert intake.raw(b"POST / HTTP/1.1\r\nContent-Length: 100\r\n\r\nabc") == 408
    assert 'event="unverified",verdict="timeout"} 1.0' in intake.get("/metrics")
    assert intake.rows() == []


def test_a_signed_body_that_is_not_a_json_object_or_has_no_delivery_id_is_400(intake: Intake) -> None:
    assert intake.post(b"[1]") == 400
    assert intake.post(delivery="") == 400
    assert intake.rows() == []


def test_every_refusal_is_counted_under_its_verdict(intake: Intake) -> None:
    intake.post(b"x" * (MAX_BODY + 1))
    intake.post(event="gollum")
    intake.post(json.dumps({"repository": {"full_name": "other/widgets"}}).encode())
    metrics = intake.get("/metrics")
    assert 'event="unverified",verdict="oversize"} 1.0' in metrics
    assert 'event="other",verdict="ignored"} 1.0' in metrics
    assert 'event="pull_request",verdict="foreign_repository"} 1.0' in metrics
