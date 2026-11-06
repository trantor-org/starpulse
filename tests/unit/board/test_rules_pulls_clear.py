"""The `pulls_clear` primitive: a cited pull request with no unresolved review thread and no conflict."""

from pathlib import Path

import pytest
from starpulse.board.model import rules
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import EventLog
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.runtime.assembly import assemble
from starpulse.runtime.config import load

from tests.unit.board.test_native import write_task
from tests.unit.board.test_native_pull_rules import PULL, review, stored

CONFIG = """
[board]
type = "native"

[[board.guards]]
on = { to = "Review" }
require = { pulls_clear = {} }
reason = "Review needs PRs with no open thread and no conflict"
"""
REFUSED = (False, "Review needs PRs with no open thread and no conflict")


def started(tmp_path: Path) -> tuple[Board, PullStore]:
    (tmp_path / "starpulse.toml").write_text(CONFIG)
    built, feed = assemble(load(tmp_path / "starpulse.toml"), tmp_path, None, ())
    write_task(tmp_path, "task-1", "In Progress", references=f"[{PULL}]")
    log = EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")
    built.start(feed, "test", log)
    return built, PullStore(log.engine)


def test_pulls_clear_lets_review_land_for_a_pr_with_no_thread_and_no_conflict(tmp_path: Path) -> None:
    built, store = started(tmp_path)
    store.save([stored()])

    assert review(built)[0] is True


def test_pulls_clear_refuses_review_for_a_pr_with_an_unresolved_thread(tmp_path: Path) -> None:
    built, store = started(tmp_path)
    store.save([{**stored(), "threads": 1}])

    assert review(built) == REFUSED


@pytest.mark.parametrize("mergeable", ["CONFLICTING", "UNKNOWN"])
def test_pulls_clear_refuses_review_for_a_conflicting_or_unknown_pr(tmp_path: Path, mergeable: str) -> None:
    built, store = started(tmp_path)
    store.save([{**stored(), "mergeable": mergeable}])

    assert review(built) == REFUSED


def test_pulls_clear_refuses_review_for_a_pr_the_store_does_not_hold(tmp_path: Path) -> None:
    built, _ = started(tmp_path)

    assert review(built) == REFUSED


def test_pulls_clear_takes_no_setting() -> None:
    with pytest.raises(ValueError, match="pulls_clear"):
        rules.load([{"on": {"to": "Review"}, "require": {"pulls_clear": {"files": []}}, "reason": "r"}])
