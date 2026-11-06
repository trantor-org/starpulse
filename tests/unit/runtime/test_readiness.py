"""`readiness` answers whether a `serve` can serve the board: the store at the schema head, the Board assembled, the
Board context's writer and every other context started in this boot, each named when it is not."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from starpulse.board.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.migrate import migrate
from starpulse.runtime.readiness import READY_STATE, readiness, stamp

BOOT = "boot-1"


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    url = f"sqlite:///{tmp_path / 'log.sqlite'}"
    engine = create_engine(url)
    migrate(engine)
    engine.dispose()
    return EventLog(url)


@pytest.fixture
def feed() -> BoardFeed:
    board = BoardFeed()
    board.ready.set()
    return board


def unready(report: dict) -> list[str]:
    return sorted(name for name, part in report["components"].items() if not part["ready"])


def test_a_migrated_store_an_assembled_board_and_started_contexts_are_ready(log: EventLog, feed: BoardFeed) -> None:
    for context in ("board", "pulls"):
        stamp(log, context, BOOT)

    report = readiness(log, feed, ["pulls", "board"], BOOT)()

    assert report["ready"] is True
    assert unready(report) == []
    assert set(report["components"]) == {"store", "board", "writer", "contexts"}


@pytest.mark.unmigrated
def test_a_store_behind_head_names_the_store(tmp_path: Path, feed: BoardFeed) -> None:
    behind = EventLog(f"sqlite:///{tmp_path / 'behind.sqlite'}")

    report = readiness(behind, feed, [], None)()

    assert report["ready"] is False
    assert unready(report) == ["store"]
    assert "not migrated" in report["components"]["store"]["detail"]


def test_a_board_not_yet_assembled_names_the_board(log: EventLog) -> None:
    report = readiness(log, BoardFeed(), [], None)()

    assert unready(report) == ["board"]


def test_a_context_not_started_in_this_boot_is_named(log: EventLog, feed: BoardFeed) -> None:
    stamp(log, "board", BOOT)

    report = readiness(log, feed, ["board", "pulls", "runs"], BOOT)()

    assert unready(report) == ["contexts"]
    assert report["components"]["contexts"]["detail"] == "not started: pulls, runs"


def test_a_stamp_of_an_earlier_boot_does_not_count(log: EventLog, feed: BoardFeed) -> None:
    stamp(log, "board", "an-earlier-boot")

    report = readiness(log, feed, ["board"], BOOT)()

    assert unready(report) == ["writer"]


def test_a_missing_board_context_names_the_writer_alone(log: EventLog, feed: BoardFeed) -> None:
    stamp(log, "pulls", BOOT)

    report = readiness(log, feed, ["board", "pulls"], BOOT)()

    assert unready(report) == ["writer"]


def test_a_serve_without_a_boot_checks_no_context(log: EventLog, feed: BoardFeed) -> None:
    report = readiness(log, feed, ["board", "pulls"], None)()

    assert report["ready"] is True
    assert report["components"]["contexts"]["detail"] == "not supervised"


def test_readiness_writes_nothing(log: EventLog, feed: BoardFeed) -> None:
    stamp(log, "board", BOOT)
    before = log.state(READY_STATE)

    readiness(log, feed, ["board"], BOOT)()

    assert log.state(READY_STATE) == before
