"""The no-Redis ingest proof's checks: the Redis guard, the event-log reader and the posted event."""

from __future__ import annotations

import json
import socket
import sqlite3

import clean_machine
import pytest
from clean_machine import cloudevent, logged, redis_answering, smoke


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
