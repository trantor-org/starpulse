"""The session-start client: `POST <url>/start/TASK-N` to the session-start service, and how its answers read."""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from starpulse.adapters.harnesses import session_start
from starpulse.adapters.harnesses.session_start import starter
from starpulse.contracts.adapters import StartFailedError


@contextmanager
def _service(status: int, body: str | bytes, delay: float = 0.0) -> Iterator[tuple[str, list[str]]]:
    """A session-start service on an ephemeral port that answers every POST with `status` and `body` after `delay`."""
    asked: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            asked.append(self.path)
            time.sleep(delay)
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", asked
    finally:
        server.shutdown()
        server.server_close()


def _starter(url: str) -> Callable[[str], str]:
    """The starter for a configured address, which is never None."""
    start = starter(url)
    assert start is not None
    return start


def test_a_started_session_answers_its_url() -> None:
    with _service(200, json.dumps({"task": "TASK-D7", "url": "https://claude.ai/code/session_01"})) as (url, asked):
        assert _starter(url)("TASK-D7") == "https://claude.ai/code/session_01"

    assert asked == ["/start/TASK-D7"]


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (502, "tmux could not start session task-7\n"),
        (504, "task-7 is running but has no Remote Control session yet; tmux attach -t task-7\n"),
    ],
)
def test_a_start_the_service_could_not_make_fails_with_its_answer(status: int, body: str) -> None:
    with _service(status, body) as (url, _), pytest.raises(StartFailedError) as failed:
        _starter(url)("TASK-D7")

    assert str(failed.value) == body.strip()


def test_a_refusal_that_is_not_utf8_still_reads() -> None:
    with _service(502, b"tmux \xff failed") as (url, _), pytest.raises(StartFailedError) as failed:
        _starter(url)("TASK-D7")

    assert str(failed.value) == "tmux � failed"


def test_a_refusal_with_no_body_names_the_status() -> None:
    with _service(502, "") as (url, _), pytest.raises(StartFailedError) as failed:
        _starter(url)("TASK-D7")

    assert str(failed.value) == "HTTP Error 502: Bad Gateway"


def test_an_address_ending_in_a_slash_keeps_its_path_and_drops_only_that_slash() -> None:
    # A path segment, because http.server folds a leading `//`; ending in X, so only the one slash may go.
    with _service(200, json.dumps({"url": "https://claude.ai/code/session_01"})) as (url, asked):
        _starter(f"{url}/relay/X/")("TASK-D7")

    assert asked == ["/relay/X/start/TASK-D7"]


def _no_answer(url: str) -> str:
    """How a failure from a service that never gave a readable answer opens."""
    return rf"^the session-start service at {re.escape(url)} did not answer: "


def test_an_unreachable_service_fails_naming_it() -> None:
    with _service(200, "{}") as (url, _):
        pass  # closed: nothing listens there now

    with pytest.raises(StartFailedError, match=_no_answer(url)):
        _starter(url)("TASK-D7")


def test_an_answer_that_is_not_json_fails_naming_the_service() -> None:
    with _service(200, "not json") as (url, _), pytest.raises(StartFailedError, match=_no_answer(url)):
        _starter(url)("TASK-D7")


def test_a_service_slower_than_the_wait_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_start, "_TIMEOUT_S", 0.2)

    with _service(200, "{}", delay=1.0) as (url, _), pytest.raises(StartFailedError, match="did not answer: timed out"):
        _starter(url)("TASK-D7")


@pytest.mark.parametrize("answer", [{}, {"url": ""}, {"url": 5}])
def test_an_answer_with_no_session_url_fails(answer: dict) -> None:
    with _service(200, json.dumps(answer)) as (url, _), pytest.raises(StartFailedError) as failed:
        _starter(url)("TASK-D7")

    assert str(failed.value) == f"the session-start service at {url} named no session for TASK-D7"


def test_without_an_address_there_is_no_starter() -> None:
    assert starter(None) is None
