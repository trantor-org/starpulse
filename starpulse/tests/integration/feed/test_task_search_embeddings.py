"""Search ranks by meaning only when an embeddings URL is configured, and is lexical, calling nothing, without one."""

import array
import json
import math
import random
import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text

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


def test_a_task_near_the_query_in_meaning_is_found_without_sharing_a_word(engine, endpoint: _Endpoint) -> None:
    index = _open(engine, Search(endpoint.url, "m"))
    index.index(_task("PROJ-1", title="Eviction policy", description="when the cache drops entries"))
    index.index(_task("PROJ-2", title="Backlog", description="queue depth"))
    index.embed_pending()

    hits = index.search("tuning knobs")  # no task holds both words, so the lexical match is empty

    assert [hit["task"] for hit in hits] == ["PROJ-1"]  # PROJ-2's vector is orthogonal to the query's
    assert hits[0]["snippet"].startswith("when the cache drops entries")


def test_a_reworded_task_clears_the_recall_floor_and_an_unrelated_one_does_not(engine, endpoint: _Endpoint) -> None:
    # The cosines mxbai-embed-large gives a reworded task's original (0.598) and an unrelated task (0.53) on the live board.
    endpoint.rules = (
        ("reworded", [1.0, 0.0]),
        ("original", [0.598, math.sqrt(1 - 0.598**2)]),
        ("unrelated", [0.53, math.sqrt(1 - 0.53**2)]),
    )
    index = _open(engine, Search(endpoint.url, "m"))
    index.index(_task("PROJ-1", title="The original"))
    index.index(_task("PROJ-2", title="Something unrelated"))
    index.embed_pending()

    assert _found(index, "reworded query") == ["PROJ-1"]


def test_a_task_is_embedded_by_its_title_and_description_alone(engine, endpoint: _Endpoint) -> None:
    index = _open(engine, Search(endpoint.url, "m"))
    index.index(
        _task("PROJ-1", title="Tuning", description="queue depth", acceptance_criteria=["tests pass"], notes="later")
    )

    index.embed_pending()

    assert endpoint.requests[0]["input"] == ["Tuning\nqueue depth"]


def test_a_vector_stored_from_the_whole_task_is_made_again_once(engine, endpoint: _Endpoint) -> None:
    _open(engine, Search(endpoint.url, "m")).index(_task("PROJ-1", title="Tuning"))
    with engine.begin() as connection:  # a vector as an earlier release stored it, keyed by the model alone
        connection.execute(
            text("INSERT INTO starpulse_task_vectors (task_row, model, vector) VALUES (:row, 'm', x'00')"),
            {"row": search_module._row("PROJ-1")},
        )
    index = _open(engine, Search(endpoint.url, "m"))

    assert index.embed_pending() == 1
    assert index.embed_pending() == 0
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM starpulse_task_vectors")).scalar() == 1


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


def test_a_repeat_search_scores_the_held_vectors_without_scanning_them_again(engine, endpoint: _Endpoint) -> None:
    index = _open(engine, Search(endpoint.url, "m"))
    _board(index)
    index.embed_pending()
    index.search("knobs")  # the first search holds the embedded tasks' vectors
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))

    index.search("knobs")

    assert [sql for sql in statements if "MATCH" not in sql] == []  # only the lexical query reads the database


def test_a_search_after_a_warm_one_sees_tasks_embedded_changed_and_removed_since(engine, endpoint: _Endpoint) -> None:
    index = _open(engine, Search(endpoint.url, "m"))
    index.index(_task("PROJ-1", title="Eviction policy", description="when the cache drops entries"))
    index.embed_pending()
    assert _found(index, "tuning knobs") == ["PROJ-1"]  # warm

    index.index(_task("PROJ-2", title="Pacing", description="queue depth"))
    index.embed_pending()
    assert _found(index, "tuning knobs") == ["PROJ-1"]  # PROJ-2's vector is orthogonal to the query's

    index.index(_task("PROJ-2", title="Pacing", description="the cache again"))
    index.embed_pending()
    assert sorted(_found(index, "tuning knobs")) == ["PROJ-1", "PROJ-2"]  # the replaced text, embedded anew

    index.remove("PROJ-1")
    assert _found(index, "tuning knobs") == ["PROJ-2"]


def test_a_search_after_one_write_reads_only_the_vector_that_write_changed(engine, endpoint: _Endpoint) -> None:
    index = _open(engine, Search(endpoint.url, "m"))
    for number in range(20):
        index.index(_task(f"PROJ-{number}", title=f"Task {number}", description="the cache"))
    index.embed_pending()
    index.search("knobs")  # warm
    index.index(_task("PROJ-99", title="Newcomer", description="the queue"))
    index.embed_pending()
    statements: list[tuple[str, object]] = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append((args[2], args[3])))

    index.search("knobs")

    reads = [(sql, params) for sql, params in statements if "MATCH" not in sql and sql.lstrip().startswith("SELECT")]
    assert len(reads) == 1  # one read, of the changed task's row alone
    assert " IN (" in reads[0][0]
    assert len(reads[0][1]) == 2  # the recipe and the one row


def test_a_write_does_not_wait_for_a_search_loading_the_vectors(engine, endpoint: _Endpoint) -> None:
    index = _open(engine, Search(endpoint.url, "m"))
    _board(index)
    index.embed_pending()
    loading, release = threading.Event(), threading.Event()

    def hold_the_load(connection, cursor, statement, *rest) -> None:
        if (
            "starpulse_task_vectors" in statement
            and "MATCH" not in statement
            and statement.lstrip().startswith("SELECT")
        ):
            loading.set()
            release.wait(timeout=10)

    event.listen(engine, "before_cursor_execute", hold_the_load)
    searcher = threading.Thread(target=index.search, args=("knobs",))
    searcher.start()
    assert loading.wait(timeout=10)
    writer = threading.Thread(target=index.index, args=(_task("PROJ-3", title="Late", description="the queue"),))
    writer.start()

    writer.join(timeout=3)
    stalled = writer.is_alive()
    release.set()
    searcher.join(timeout=10)
    writer.join(timeout=10)

    assert not stalled


def test_five_thousand_embedded_tasks_are_scored_in_under_a_tenth_of_a_second(engine, endpoint: _Endpoint) -> None:
    dimension, count = 1024, 5000
    rng = random.Random(7)
    query = array.array("f", (rng.random() - 0.5 for _ in range(dimension)))
    endpoint.vector = lambda text: list(query)
    index = _open(engine, Search(endpoint.url, "m"))
    vectors: dict[str, array.array] = {}
    with engine.begin() as connection:
        for number in range(count):
            noise = array.array("f", (rng.random() - 0.5 for _ in range(dimension)))
            weight = number / count / 2  # each task a little nearer the query than the last (cosine to 0.7), none tied
            held = array.array("f", (weight * q + (1 - weight) * n for q, n in zip(query, noise, strict=True)))
            task_id, row = f"PROJ-{number}", search_module._row(f"PROJ-{number}")
            vectors[task_id] = held
            connection.execute(
                search_module._INSERT,
                {
                    "row": row,
                    "task": task_id,
                    "title": task_id,
                    "description": "d",
                    "criteria": "",
                    "notes": "",
                    "lane": "to_do",
                    "digest": task_id,
                },
            )
            connection.execute(
                text("INSERT INTO starpulse_task_vectors (task_row, model, vector) VALUES (:row, :model, :vector)"),
                {"row": row, "model": index._recipe, "vector": held.tobytes()},
            )
    expected = sorted(
        ((task_id, search_module._cosine(query, held)) for task_id, held in vectors.items()),
        key=lambda pair: -pair[1],
    )
    expected = [(task_id, sim) for task_id, sim in expected if sim >= search_module._RECALL_FLOOR][:10]
    assert expected  # the floor leaves hits to compare
    index.search("zzz")  # warm

    started = time.perf_counter()
    hits = index.search("zzz")
    elapsed = time.perf_counter() - started

    assert [hit["task"] for hit in hits] == [task_id for task_id, _ in expected]
    for hit, (_, similarity) in zip(hits, expected, strict=True):
        assert hit["score"] == pytest.approx((1 - search_module._LEXICAL_WEIGHT) * similarity, abs=1e-4)
    assert elapsed < 0.1
