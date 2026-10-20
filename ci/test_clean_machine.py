"""The no-Redis ingest proof's checks: the Redis guard, the event-log reader and the posted event."""

from __future__ import annotations

import json
import socket
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import clean_machine
import pytest
from clean_machine import Placed, cloudevent, logged, redis_answering, smoke


@pytest.fixture
def listener():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        yield sock.getsockname()[1]


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_redis_answering_names_the_port_that_accepts_a_connection(listener):
    assert redis_answering((closed_port(), listener)) == [listener]


def test_redis_answering_is_empty_when_no_port_answers():
    assert redis_answering((closed_port(), closed_port())) == []


def test_the_proof_fails_before_serving_when_a_redis_port_answers(listener, monkeypatch):
    monkeypatch.setattr(clean_machine, "REDIS_PORTS", (listener,))

    problem = smoke("/nonexistent/python", 1)

    assert problem == f"a Redis port answers on [{listener}]: the proof needs a machine without one"


def write_log(directory, *entries):
    with sqlite3.connect(directory / "events.sqlite") as connection:
        connection.execute("create table starpulse_events (id integer primary key, stream text, fields text)")
        connection.executemany(
            "insert into starpulse_events (stream, fields) values (?, ?)",
            [(stream, json.dumps(fields)) for stream, fields in entries],
        )


def test_logged_reads_the_machine_events_in_order_and_skips_other_streams(tmp_path):
    write_log(
        tmp_path,
        ("machine:events", {"event": "BUILT", "run": "r1"}),
        ("runs:events", {"event": "StepStarted", "run_id": "r1"}),
        ("machine:events", {"event": "SHIPPED", "run": "r1"}),
    )

    assert logged(tmp_path) == [("BUILT", "r1"), ("SHIPPED", "r1")]


def test_logged_is_empty_before_serve_creates_the_table(tmp_path):
    sqlite3.connect(tmp_path / "events.sqlite").close()

    assert logged(tmp_path) == []


def test_the_posted_event_is_keyed_by_run_and_names_its_producer_machine_and_actor():
    assert cloudevent("e1", "BUILT", "r1") == {
        "specversion": "1.0",
        "id": "e1",
        "source": "builder",
        "type": "BUILT",
        "run": "r1",
        "machine": "delivery",
        "actor": "ci",
    }


def serve_stream(body: str):
    """A server whose `/api/events` sends `body` and closes."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    return server


def snapshot(*flows):
    return f"event: snapshot\ndata: {json.dumps({'flows': [{'name': n, 'agents': [{'id': i} for i in ids]} for n, ids in flows]})}\n\n"


def placed_from(body: str) -> set:
    server = serve_stream(body)
    try:
        stream = Placed(server.server_port)
        assert stream.opened.wait(5)
        time.sleep(0.5)  # the server has closed after sending, so the reader has taken every frame by now
        return stream.tasks
    finally:
        server.shutdown()


def test_a_move_event_places_its_task():
    move = 'event: move\ndata: {"flow": "delivery", "id": "r1"}\n\n'

    assert placed_from(snapshot(("delivery", [])) + move) == {("delivery", "r1")}


def test_a_snapshot_after_the_first_places_the_tasks_a_replaying_machine_held():
    assert placed_from(snapshot(("delivery", [])) + snapshot(("delivery", ["r1"]))) == {("delivery", "r1")}


def test_the_snapshot_held_at_open_places_nothing_so_it_cannot_stand_for_a_posted_event():
    assert placed_from(snapshot(("delivery", ["r1"]))) == set()
