"""The `events` consumer as a `contexts` thread and the `starpulse github` command that settles its dead deliveries."""

from __future__ import annotations

import dataclasses
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from starpulse.__main__ import COMMANDS
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.migrate import migrate_chain
from starpulse.github.adapters.outbound.inbox import SqlInbox
from starpulse.github.adapters.outbound.queue import SqlQueue
from starpulse.github.model.delivery import Delivery
from starpulse.github.model.github_config import GitHub
from starpulse.runtime.config import Producer, load
from starpulse.runtime.contexts import contexts_of, default_starters

PULL = b'{"action": "closed", "repository": {"full_name": "acme/widgets"}, "number": 7}'


def _config(tmp_path: Path, *, producers: tuple[Producer, ...]):
    table = GitHub(secret_env="GH_SECRET", organisation="acme", database_url=f"sqlite:///{tmp_path / 'github.sqlite'}")
    return dataclasses.replace(load(None), github=table, producers=producers)


def test_the_events_context_runs_only_with_a_github_table_and_a_github_producer(tmp_path: Path) -> None:
    producer = Producer("github", "GH_TOKEN", ("github-pull-request",), ("github",))

    assert "github-events" in contexts_of(_config(tmp_path, producers=(producer,)))
    assert "github-events" not in contexts_of(_config(tmp_path, producers=()))
    assert "github-events" not in contexts_of(load(None))


def test_the_events_context_refuses_to_start_without_the_producer_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    config = _config(tmp_path, producers=(Producer("github", "GH_TOKEN", (), ()),))
    stop = threading.Event()
    start = default_starters(config, None, tmp_path, EventLog(f"sqlite:///{tmp_path / 'e.sqlite'}"), ["github-events"], stop)

    with pytest.raises(ValueError, match="token"):
        start["github-events"](stop)


@pytest.fixture
def dead(tmp_path: Path) -> Path:
    config = tmp_path / "starpulse.toml"
    config.write_text(
        f'[github]\nsecret_env = "GH_SECRET"\norganisation = "acme"\ndatabase_url = "sqlite:///{tmp_path / "github.sqlite"}"\n'
    )
    inbox = SqlInbox(f"sqlite:///{tmp_path / 'github.sqlite'}", migrate_chain)
    inbox.save(Delivery("d-1", "pull_request", "closed", "acme/widgets", PULL))
    queue = SqlQueue(inbox.engine, "events")
    queue.claim()
    queue.fail("d-1", "ingest answered 400", fatal=True)
    inbox.engine.dispose()
    return config


def _status(tmp_path: Path) -> str:
    with create_engine(f"sqlite:///{tmp_path / 'github.sqlite'}").connect() as db:
        return db.execute(text("SELECT status FROM github_inbox_state WHERE delivery_id = 'd-1'")).scalar_one()


@pytest.mark.parametrize(("action", "status"), [("requeue", "pending"), ("dismiss", "skipped")])
def test_the_command_settles_a_dead_delivery_once(
    dead: Path, tmp_path: Path, action: str, status: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert COMMANDS["github"]([action, "d-1", "--config", str(dead)]) == 0
    assert _status(tmp_path) == status

    assert COMMANDS["github"]([action, "d-1", "--config", str(dead)]) == 1
    assert "not a dead delivery" in capsys.readouterr().err
