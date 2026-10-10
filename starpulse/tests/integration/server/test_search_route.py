"""`GET /api/search?q=`: the board's tasks matching every word of a query, best first, from the instance's own index."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.feed.search import SearchIndex
from starpulse._internal.kit.adapter_kit import serve, task, url


def _get(server: ThreadingHTTPServer, path: str) -> tuple[int, dict | None]:
    try:
        with urllib.request.urlopen(url(server, path), timeout=5) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except ValueError:
            return exc.code, None


@pytest.fixture
def server(tmp_path: Path) -> Iterator[ThreadingHTTPServer]:
    index = SearchIndex.open(create_engine(f"sqlite:///{tmp_path / 'search.sqlite'}"))
    assert index is not None
    index.index(task("PROJ-1", "To Do", title="Rotate the signing keys", description="Cycle the authority"))
    index.index(task("PROJ-2", "Done", title="Signing audit", settled="completed"))
    index.index(task("PROJ-3", "To Do", title="Unrelated", description="mentions signing once"))
    with serve(tmp_path, search=index) as server:
        yield server


def test_a_query_answers_the_matching_tasks_best_first(server: ThreadingHTTPServer) -> None:
    status, body = _get(server, "/api/search?q=signing")

    assert status == 200
    assert body is not None
    assert body["query"] == "signing"
    assert [(hit["task"], hit["lane"]) for hit in body["hits"]] == [
        ("PROJ-2", "completed"),
        ("PROJ-1", "to_do"),
        ("PROJ-3", "to_do"),
    ]
    assert set(body["hits"][0]) == {"task", "title", "lane", "score", "snippet"}


def test_a_query_with_no_match_answers_no_hits(server: ThreadingHTTPServer) -> None:
    assert _get(server, "/api/search?q=nothing") == (200, {"query": "nothing", "hits": []})


def test_the_limit_caps_the_hits(server: ThreadingHTTPServer) -> None:
    status, body = _get(server, "/api/search?q=signing&limit=2")

    assert status == 200
    assert body is not None
    assert len(body["hits"]) == 2


@pytest.mark.parametrize("query", ["", "q=", "q=%20%20", "q=a&limit=0", "q=a&limit=101", "q=a&limit=many"])
def test_a_missing_or_blank_query_or_a_limit_out_of_range_is_400(server: ThreadingHTTPServer, query: str) -> None:
    status, body = _get(server, f"/api/search?{query}")

    assert status == 400
    assert body is not None
    assert "error" in body


def test_a_server_that_keeps_no_index_answers_404(tmp_path: Path) -> None:
    with serve(tmp_path) as server:
        status, body = _get(server, "/api/search?q=signing")

    assert (status, body) == (404, {"error": "this server keeps no search index"})
