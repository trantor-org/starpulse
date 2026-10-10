"""Search ranks by meaning only when an embeddings URL is configured, and is lexical, calling nothing, without one."""

import json
import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.config.search import Search
from starpulse._internal.feed import search as search_module
from starpulse._internal.feed.search import EmbeddingError, SearchIndex
from starpulse.contracts.adapters import BoardTask


def _task(task_id: str, **fields: object) -> BoardTask:
    return BoardTask.model_validate({"id": task_id, "team": "demo", "title": "t", "lane": "to_do", **fields})


class _Endpoint:
    """A stub OpenAI-compatible embeddings endpoint. A text's vector is the first of `rules` whose word it holds."""

    rules = (("cache", [1.0, 0.0]), ("queue", [0.0, 1.0]), ("tuning", [1.0, 0.0]))

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.authorizations: list[str | None] = []
        self.failing = False
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                endpoint.requests.append(body)
                endpoint.authorizations.append(self.headers.get("Authorization"))
                if endpoint.failing:
                    self.send_response(503)
                    self.end_headers()
                    return
                data = [{"index": at, "embedding": endpoint.vector(text)} for at, text in enumerate(body["input"])]
                payload = json.dumps({"data": data}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/v1/embeddings"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def vector(self, text: str) -> list[float]:
        return next((vector for word, vector in self.rules if word in text.lower()), [0.0, 0.0])

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def endpoint() -> Iterator[_Endpoint]:
    stub = _Endpoint()
    yield stub
    stub.close()


@pytest.fixture
def engine(tmp_path: Path):
    return create_engine(f"sqlite:///{tmp_path / 'search.sqlite'}")


def _open(engine, settings: Search | None) -> SearchIndex:
    opened = SearchIndex.open(engine, settings)
    assert opened is not None
    return opened


def _board(index: SearchIndex) -> None:
    """Two tasks a query for `tuning` finds: the first by its title, the second only by its description."""
    index.index(_task("PROJ-1", title="Tuning", description="queue depth"))
    index.index(_task("PROJ-2", title="Latency", description="notes on tuning the cache"))


def _found(index: SearchIndex, query: str) -> list[str]:
    return [hit["task"] for hit in index.search(query)]


def test_without_an_embeddings_url_search_is_lexical_and_nothing_calls_out(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("search opened a network connection without an embeddings URL")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    index = _open(engine, Search())

    _board(index)

    assert index.embed_pending() == 0
    assert _found(index, "tuning") == ["PROJ-1", "PROJ-2"]


def test_a_configured_endpoint_re_ranks_the_lexical_hits_by_its_vectors(engine, endpoint: _Endpoint) -> None:
    index = _open(engine, Search(endpoint.url, "embed-small"))
    _board(index)
    assert _found(index, "tuning") == ["PROJ-1", "PROJ-2"]  # lexical only until the tasks are embedded

    assert index.embed_pending() == 2
    hits = index.search("tuning")

    assert [hit["task"] for hit in hits] == ["PROJ-2", "PROJ-1"]  # the title match yields to the nearer meaning
    assert hits[0]["score"] > hits[1]["score"]
    assert {request["model"] for request in endpoint.requests} == {"embed-small"}
    assert endpoint.requests[-1]["input"] == ["tuning"]  # the query is embedded once per search


def test_a_task_is_embedded_once_until_its_text_changes(engine, endpoint: _Endpoint) -> None:
    index = _open(engine, Search(endpoint.url, "m"))
    index.index(_task("PROJ-1", title="Tuning"))
    assert index.embed_pending() == 1

    index.index(_task("PROJ-1", title="Tuning"))
    assert index.embed_pending() == 0

    index.index(_task("PROJ-1", title="Tuning the cache"))
    assert index.embed_pending() == 1


def test_a_task_embedded_by_another_model_is_embedded_again(engine, endpoint: _Endpoint) -> None:
    first = _open(engine, Search(endpoint.url, "m1"))
    first.index(_task("PROJ-1", title="Tuning"))
    assert first.embed_pending() == 1

    assert _open(engine, Search(endpoint.url, "m2")).embed_pending() == 1


def test_an_endpoint_that_fails_leaves_search_lexical(engine, endpoint: _Endpoint) -> None:
    index = _open(engine, Search(endpoint.url, "m"))
    _board(index)
    assert index.embed_pending() == 2
    endpoint.failing = True

    assert _found(index, "tuning") == ["PROJ-1", "PROJ-2"]  # the query cannot be embedded, so the lexical order stands
    index.index(_task("PROJ-3", title="Tuning again"))
    with pytest.raises(EmbeddingError):
        index.embed_pending()


def test_the_bearer_token_comes_from_the_variable_the_table_names(
    engine, endpoint: _Endpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMBEDDINGS_TOKEN", "s3cret")
    index = _open(engine, Search(endpoint.url, "m", "EMBEDDINGS_TOKEN"))
    index.index(_task("PROJ-1", title="Tuning"))

    index.embed_pending()

    assert endpoint.authorizations == ["Bearer s3cret"]


def test_the_keeping_loop_catches_the_vectors_up_until_it_is_stopped(
    engine, endpoint: _Endpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(search_module, "_POLL", 0.01)
    index = _open(engine, Search(endpoint.url, "m"))
    _board(index)
    stop = threading.Event()
    thread = threading.Thread(target=index.keep_embedding, args=(stop,), daemon=True)
    thread.start()

    deadline = time.monotonic() + 5
    while _found(index, "tuning") != ["PROJ-2", "PROJ-1"] and time.monotonic() < deadline:
        time.sleep(0.02)
    stop.set()
    thread.join(timeout=5)

    assert _found(index, "tuning") == ["PROJ-2", "PROJ-1"]
    assert not thread.is_alive()
