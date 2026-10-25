"""Intent classification: a configured typed-decision endpoint names a human prompt's intent, and any failure of it
leaves the label empty."""

import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from starpulse._internal.config.analytics import Analytics, Labeller
from starpulse.harness_telemetry.telemetry import signals
from starpulse.tests.unit.harness_telemetry.test_telemetry import claude, export

CRITERIA = {"correction": "The agent erred.", "approval": "Proceed."}


@contextmanager
def stub(
    answer: Callable[[dict[str, Any]], tuple[float, dict[str, Any]]],
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """A labeller endpoint whose reply to each request is `answer(request)` as (seconds to wait, body); the requests it
    got are listed beside its URL."""
    seen: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(request)
            wait, body = answer(request)
            time.sleep(wait)
            payload = json.dumps(body).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except OSError:  # the client gave up on a slow answer
                pass

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1/systemone", seen
    finally:
        server.shutdown()
        server.server_close()


def labeller(url: str, timeout: float = 2.0) -> Analytics:
    return Analytics(labeller=Labeller(url=url, model="intent", criteria=CRITERIA, timeout=timeout))


def prompts(analytics: Analytics, *texts: str) -> list[str]:
    body = export(*(claude("user_prompt", n, prompt=text) for n, text in enumerate(texts, 1)))
    return [s.label for s in signals(body, analytics=analytics) if s.kind == "prompt"]


def answer(choice: str) -> Callable[[dict[str, Any]], tuple[float, dict[str, Any]]]:
    return lambda _request: (0.0, {"answers": {"intent": {"choice": choice}}})


def test_a_human_prompt_carries_the_label_the_endpoint_chose_and_the_endpoint_got_its_text_and_the_labels() -> None:
    with stub(answer("correction")) as (url, seen):
        assert prompts(labeller(url), "that was wrong, undo it") == ["correction"]

    (request,) = seen
    assert request["state"] == "that was wrong, undo it"
    assert request["model"] == "intent"
    assert request["questions"]["intent"]["type"] == "choice"
    assert request["questions"]["intent"]["criteria"] == CRITERIA


def test_an_answer_that_is_not_a_configured_label_is_unsure() -> None:
    with stub(answer("poetry")) as (url, _):
        assert prompts(labeller(url), "hm") == ["unsure"]


def test_an_injected_prompt_is_not_sent_to_the_endpoint() -> None:
    with stub(answer("approval")) as (url, seen):
        analytics = Analytics(injected_openings=("<task-notification",), labeller=Labeller(url, "intent", CRITERIA))
        assert prompts(analytics, "<task-notification>done", "go on") == ["", "approval"]

    assert [r["state"] for r in seen] == ["go on"]


def test_no_labeller_leaves_every_label_empty() -> None:
    assert prompts(Analytics(), "go on") == [""]


def test_an_unreachable_endpoint_leaves_the_label_empty() -> None:
    with stub(answer("approval")) as (url, _):
        pass  # the server is closed once the block ends

    assert prompts(labeller(url), "go on") == [""]


def test_an_endpoint_slower_than_the_timeout_leaves_the_label_empty_within_the_timeout() -> None:
    with stub(lambda _request: (3.0, {"answers": {"intent": {"choice": "approval"}}})) as (url, _):
        started = time.monotonic()
        found = prompts(labeller(url, timeout=0.3), "go on")
        elapsed = time.monotonic() - started

    assert found == [""]
    assert elapsed < 1.5


def test_an_endpoint_that_answers_nothing_usable_leaves_the_label_empty() -> None:
    for body in ({}, {"answers": None}, {"answers": {"intent": {}}}, [1]):
        with stub(lambda _request, body=body: (0.0, body)) as (url, _):
            assert prompts(labeller(url), "go on") == [""]
