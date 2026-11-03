"""The GitHub intake as a `contexts` thread: `[github]` makes `serve` listen, no table starts none, and stopping closes it."""

import dataclasses
import hashlib
import hmac
import socket
import threading
import time
import urllib.request
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from starpulse.event_log.event_log import EventLog
from starpulse.github.model.github_config import GitHub
from starpulse.runtime.config import load
from starpulse.runtime.contexts import contexts_of, default_starters

WAIT_S = 5.0
SECRET = "context-secret"
BODY = b'{"repository": {"full_name": "acme/widgets"}}'


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def test_a_deployment_without_a_github_table_starts_no_listener() -> None:
    assert "github" not in contexts_of(load(None))


def test_the_github_context_saves_a_delivery_and_closes_its_port_when_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TEST_SECRET", SECRET)
    port = _free_port()
    database = f"sqlite:///{tmp_path / 'github.sqlite'}"
    table = GitHub(secret_env="GITHUB_TEST_SECRET", organisation="acme", database_url=database, port=port)
    config = dataclasses.replace(load(None), github=table)
    assert "github" in contexts_of(config)
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    stop = threading.Event()
    start = default_starters(config, None, tmp_path, log, ["github"], stop)["github"]

    start(stop)
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/",
            data=BODY,
            headers={
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "ctx-1",
                "X-Hub-Signature-256": "sha256=" + hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest(),
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=WAIT_S) as response:
            assert response.status == 202
        with create_engine(database).connect() as db:
            assert db.execute(text("SELECT delivery_id FROM github_inbox")).scalars().all() == ["ctx-1"]
    finally:
        stop.set()

    deadline = time.monotonic() + WAIT_S
    while _listening(port) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _listening(port)
