"""The runs stream contract: its entry shape and the Redis its producer reaches."""

from __future__ import annotations

import pytest

from starpulse import run_events


def test_an_entry_omits_the_step_and_depends_of_a_run_level_event() -> None:
    assert run_events.entry("end", "w", "r", "failed", now=5.0) == {
        "time": 5.0,
        "phase": "end",
        "workflow": "w",
        "run_id": "r",
        "status": "failed",
    }


def test_the_producer_reaches_the_redis_url_names() -> None:
    producer = run_events.producer({"REDIS_URL": "redis://:s3cret@cache:6400"})

    assert (producer.stream, producer.redis_host, producer.redis_port, producer.redis_password) == (
        "runs:events",
        "cache",
        6400,
        "s3cret",
    )


def test_a_redis_url_without_a_port_or_password_uses_redis_defaults_and_the_shared_password() -> None:
    producer = run_events.producer({"REDIS_URL": "redis://cache.lan", "REDIS_PASSWORD": "shared"})

    assert (producer.redis_host, producer.redis_port, producer.redis_password) == ("cache.lan", 6379, "shared")


def test_without_a_redis_url_the_producer_reads_the_runs_endpoint_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUNS_REDIS_HOST", "runs.lan")
    monkeypatch.setenv("RUNS_REDIS_PORT", "6401")

    producer = run_events.producer({})

    assert (producer.stream, producer.redis_host, producer.redis_port) == ("runs:events", "runs.lan", 6401)


def test_a_redis_url_without_a_host_reaches_the_local_redis() -> None:
    producer = run_events.producer({"REDIS_URL": "redis://:s3cret@:6400"})

    assert (producer.redis_host, producer.redis_port, producer.redis_password) == ("127.0.0.1", 6400, "s3cret")
