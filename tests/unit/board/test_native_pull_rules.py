"""The native board's pull request primitives: `pulls_ready` and `pulls_changed` read the PR store, never GitHub."""

from pathlib import Path
from typing import Any

import pytest
from starpulse.board.adapters.native import board
from starpulse.board.model import rules
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import EventLog
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.runtime.assembly import assemble
from starpulse.runtime.config import load

from tests.unit.board.test_native import write_task

PULL = "https://github.com/acme/app/pull/5"
OTHER = "https://github.com/acme/app/pull/6"
CONFIG = """
[board]
type = "native"

[[board.guards]]
on = { to = "Review" }
require = { pulls_ready = {} }
reason = "Review needs ready PRs with green checks"

[[board.guards]]
on = { to = "Review" }
require = { pulls_changed = { files = ["src/web/**", "*.html"], matches = "render evidence" } }
reason = "a page change needs render evidence"
"""
CRITERIA = "<!-- AC:BEGIN -->\n- [{mark}] #1 render evidence on the PR\n<!-- AC:END -->\n"


def stored(number: int = 5, *, draft: bool = False, checks: str = "pass", files: list[str] | None = None, body: str = "") -> dict[str, Any]:
    """One PR record as the store keeps it."""
    return {
        "repo": "acme/app",
        "number": number,
        "state": "OPEN",
        "isDraft": draft,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefOid": "abc",
        "body": body,
        "checks": checks,
        "requiredChecks": [],
        "threads": 0,
        "updatedAt": "2026-11-02T00:00:00Z",
        "mergedAt": None,
        "mergeSha": None,
        "fetchedAt": 0.0,
        "detail": {"files": ["README.md"] if files is None else files},
    }


def started(tmp_path: Path) -> tuple[Board, PullStore, Path]:
    """The board `CONFIG` declares, started on a store in `tmp_path`, holding `task-1` In Progress citing `PULL`."""
    (tmp_path / "starpulse.toml").write_text(CONFIG)
    built, feed = assemble(load(tmp_path / "starpulse.toml"), tmp_path, None, ())
    path = write_task(tmp_path, "task-1", "In Progress", references=f"[{PULL}]")
    log = EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")
    built.start(feed, "test", log)
    return built, PullStore(log.engine), path


def review(built: Board) -> tuple[bool, str]:
    assert built.writer is not None
    written = built.writer("task-1", "Review", "agent")
    return written.ok, written.output


def test_pulls_ready_refuses_review_while_a_cited_pr_is_draft(tmp_path: Path) -> None:
    built, store, _ = started(tmp_path)
    store.save([stored(draft=True)])

    assert review(built) == (False, "Review needs ready PRs with green checks")


@pytest.mark.parametrize("checks", ["failing", "pending", "none"])
def test_pulls_ready_refuses_review_while_checks_do_not_pass(tmp_path: Path, checks: str) -> None:
    built, store, _ = started(tmp_path)
    store.save([stored(checks=checks)])

    assert review(built) == (False, "Review needs ready PRs with green checks")


def test_pulls_ready_refuses_review_for_a_pr_the_store_does_not_hold(tmp_path: Path) -> None:
    built, _, _ = started(tmp_path)

    assert review(built)[0] is False


def test_pulls_ready_lets_review_land_once_every_cited_pr_is_ready_and_green(
    tmp_path: Path,
) -> None:
    built, store, path = started(tmp_path)
    path.write_text(path.read_text().replace(f"[{PULL}]", f"[{PULL}, {OTHER}]"))
    store.save([stored(5), stored(6, draft=True)])
    assert review(built)[0] is False

    store.save([stored(6)])

    assert review(built)[0] is True


def test_pulls_changed_refuses_review_when_files_match_and_no_evidence_is_given(
    tmp_path: Path,
) -> None:
    built, store, _ = started(tmp_path)
    store.save([stored(files=["src/web/page.js"])])

    assert review(built) == (False, "a page change needs render evidence")


@pytest.mark.parametrize("path", ["src/web/page.js", "index.html"])
def test_pulls_changed_judges_each_glob(tmp_path: Path, path: str) -> None:
    built, store, _ = started(tmp_path)
    store.save([stored(files=[path])])

    assert review(built)[0] is False


def test_pulls_changed_holds_when_no_changed_file_matches(tmp_path: Path) -> None:
    built, store, _ = started(tmp_path)
    store.save([stored(files=["docs/readme.md"])])

    assert review(built)[0] is True


def test_pulls_changed_holds_for_a_checked_criterion_matching_the_pattern(
    tmp_path: Path,
) -> None:
    built, store, path = started(tmp_path)
    store.save([stored(files=["src/web/page.js"])])
    path.write_text(path.read_text() + CRITERIA.format(mark=" "))
    assert review(built)[0] is False  # an unchecked criterion is no evidence

    path.write_text(path.read_text().replace("- [ ]", "- [x]"))

    assert review(built)[0] is True


def test_pulls_changed_holds_for_a_pr_body_matching_the_pattern(tmp_path: Path) -> None:
    built, store, _ = started(tmp_path)
    store.save([stored(files=["src/web/page.js"], body="## Render evidence\nrender evidence: shot.png")])

    assert review(built)[0] is True


def test_pulls_changed_refuses_a_pr_whose_files_the_store_does_not_know(tmp_path: Path) -> None:
    built, store, _ = started(tmp_path)
    record = stored()
    record["detail"] = None
    store.save([record])

    assert review(built)[0] is False


def test_a_board_that_has_not_started_holds_no_pr_so_ready_refuses(tmp_path: Path) -> None:
    (tmp_path / "starpulse.toml").write_text(CONFIG)
    board({}, tmp_path)
    write_task(tmp_path, "task-1", "In Progress", references=f"[{PULL}]")
    built = board(load(tmp_path / "starpulse.toml").board, tmp_path)

    assert review(built)[0] is False


def test_the_standing_verdict_leaves_out_a_rule_that_read_the_pr_store() -> None:
    declared = [{"on": {"to": "Review"}, "require": {"pulls_ready": {}}, "reason": "r"}]
    front = {"id": "task-1", "status": "In Progress", "references": [PULL]}

    assert rules.standing_refusal(rules.load(declared), front, "", "Review") is None


@pytest.mark.parametrize(
    ("require", "fragment"),
    [
        ({"pulls_ready": {"x": 1}}, "no key x"),
        ({"pulls_changed": {"matches": "a"}}, "files"),
        ({"pulls_changed": {"files": [], "matches": "a"}}, "files"),
        ({"pulls_changed": {"files": ["a"]}}, "matches"),
        ({"pulls_changed": {"files": ["a"], "matches": "("}}, "regular expression"),
    ],
)
def test_a_pull_primitive_it_cannot_read_is_a_startup_error(require: dict[str, Any], fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        rules.load([{"on": {"to": "Review"}, "require": require, "reason": "r"}])

