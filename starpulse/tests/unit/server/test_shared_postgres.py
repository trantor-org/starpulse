"""The Postgres the xdist workers of one run share: how the controller hands over its address, and a database per worker."""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import text

from starpulse.tests.shared_postgres import (
    publish_error,
    publish_url,
    request_service,
    serve_requests,
    wait_for_url,
    worker_database,
)


def test_a_worker_gets_the_url_the_controller_published(tmp_path):
    publish_url(tmp_path, "postgresql+psycopg://u:p@localhost:5432/test")
    assert wait_for_url(tmp_path, timeout=5) == "postgresql+psycopg://u:p@localhost:5432/test"


def test_a_worker_waits_for_a_url_published_while_it_waits(tmp_path):
    threading.Timer(0.3, publish_url, (tmp_path, "postgresql://later")).start()
    assert wait_for_url(tmp_path, timeout=10) == "postgresql://later"


def test_the_controller_starts_each_service_a_worker_requests_once_and_no_other(tmp_path):
    started, stop = [], threading.Event()
    server = threading.Thread(target=serve_requests, args=(tmp_path, started.append, stop), kwargs={"poll": 0.01})
    server.start()
    request_service(tmp_path, "postgres")
    request_service(tmp_path, "postgres")
    threading.Event().wait(0.2)
    stop.set()
    server.join(timeout=5)
    assert started == ["postgres"]


def test_a_start_that_failed_fails_the_worker_with_its_reason(tmp_path):
    publish_error(tmp_path, "docker daemon is down")
    with pytest.raises(RuntimeError, match="docker daemon is down"):
        wait_for_url(tmp_path, timeout=5)


def test_no_answer_in_time_fails_the_worker(tmp_path):
    with pytest.raises(TimeoutError):
        wait_for_url(tmp_path, timeout=0.2)


def test_each_worker_database_is_its_own_and_is_dropped_afterwards(pg_engine):
    with worker_database(pg_engine.url, "gw0") as first, worker_database(pg_engine.url, "gw1") as second:
        assert first.url.database != second.url.database
        with first.begin() as db:
            db.execute(text("CREATE TABLE marker (id int)"))
        with second.connect() as db:
            assert db.execute(text("SELECT to_regclass('marker')")).scalar() is None
        name = first.url.database
    with pg_engine.connect() as db:
        assert db.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}).first() is None

