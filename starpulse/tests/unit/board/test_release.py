"""A Waiting task moves to Ready once every dependency settles; a pinned repository's dependency settles on its bump."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine

from starpulse._internal.board.release import Releaser
from starpulse._internal.board.seam import Written
from starpulse._internal.config.config import Repo
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.pulls.pulls import PullStore

CHILD, PARENT = "c" * 40, "p" * 40
CHILD_PR = "https://github.com/acme/starpulse/pull/10"
OTHER_PR = "https://github.com/acme/widgets/pull/7"
REPOS = [Repo(name="starpulse", path="starpulse", applied_by="pin-bump")]
WHEN = "2026-10-06T21:14:09Z"
LATER = "2026-10-07T09:00:00Z"
NEEDS_CRITERIA = "## Start Criteria\n```yaml\nstart_criteria:\n  - id: soak\n    kind: prom\n    expr: up\n    equals: 1\n```\n"


class Edits:
    """A task editor that records each write it is given."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any], str | Sequence[str]]] = []

    def __call__(self, name: str, changes: Mapping[str, Any], comment: str | Sequence[str], /) -> Written:
        self.calls.append((name, changes, comment))
        return Written(True, "")

    @property
    def moved(self) -> list[str]:
        return [name for name, changes, _ in self.calls if changes == {"status": "ready"}]


class Pins:
    """The parent's pointer reads: `main`'s bump PR pins `CHILD` at `starpulse`; a child contains a commit it equals."""

    def pointer(self, repo: str, sha: str, path: str) -> str | None:
        return CHILD if (repo, sha, path) == ("acme/trantor", PARENT, "starpulse") else None

    def reaches(self, repo: str, sha: str, pointer: str) -> bool:
        return sha == pointer


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


def _pull(repo: str, number: int, *, state: str, sha: str | None, at: str | None, files: Sequence[str] = ()) -> dict:
    return {
        "repo": repo,
        "number": number,
        "state": state,
        "isDraft": False,
        "mergeable": "UNKNOWN",
        "baseRefName": "main",
        "headRefOid": f"{number:040x}",
        "body": "",
        "checks": "pass",
        "requiredChecks": [],
        "threads": 0,
        "updatedAt": at or WHEN,
        "mergedAt": at,
        "mergeSha": sha,
        "fetchedAt": 0.0,
        "detail": {"mergedAt": at, "mergeSha": sha, "behindMain": 0, "files": list(files), "ci": {}},
    }


def _board(*tasks: Any) -> BoardFeed:
    feed = BoardFeed()
    for each in tasks:
        feed.put(each)
    return feed


def _release(feed: BoardFeed, store: PullStore, settle: str | None = None) -> list[str]:
    edits = Edits()
    Releaser(feed, store, edits, repos=REPOS, settle=settle, pins=Pins()).release()
    return edits.moved


def test_a_waiting_task_whose_dependencies_are_all_done_moves_to_ready(store: PullStore) -> None:
    feed = _board(
        task("TASK-1", "Done"),
        task("TASK-2", "Done"),
        task("TASK-3", "Waiting", dependencies=("TASK-1", "TASK-2")),
    )
    edits = Edits()

    moved = Releaser(feed, store, edits).release()

    assert moved == ["TASK-3"]
    assert [(name, changes) for name, changes, _ in edits.calls] == [("TASK-3", {"status": "ready"})]


def test_a_task_with_an_open_dependency_stays_waiting(store: PullStore) -> None:
    feed = _board(
        task("TASK-1", "Done"),
        task("TASK-2", "In Progress"),
        task("TASK-3", "Waiting", dependencies=("TASK-1", "TASK-2")),
    )

    assert _release(feed, store) == []


def test_a_board_with_no_dependencies_has_nothing_to_release(store: PullStore) -> None:
    feed = _board(task("TASK-1", "Waiting"), task("TASK-2", "Ready"), task("TASK-3", "Done"))

    assert _release(feed, store) == []


def test_only_waiting_tasks_are_released(store: PullStore) -> None:
    feed = _board(
        task("TASK-1", "Done"),
        task("TASK-2", "In Progress", dependencies=("TASK-1",)),
        task("TASK-3", "Review", dependencies=("TASK-1",)),
    )

    assert _release(feed, store) == []


def test_a_task_gated_by_start_criteria_is_left_to_them(store: PullStore) -> None:
    feed = _board(
        task("TASK-1", "Done"),
        task("TASK-2", "Waiting", dependencies=("TASK-1",), description=NEEDS_CRITERIA),
    )

    assert _release(feed, store) == []


def test_a_completed_dependency_is_done(store: PullStore) -> None:
    feed = _board(
        task("TASK-1", "Done", settled="completed", settled_at=5.0),
        task("TASK-2", "Waiting", dependencies=("TASK-1",)),
    )

    assert _release(feed, store) == ["TASK-2"]


def test_an_archived_dependency_never_releases_its_dependent(store: PullStore) -> None:
    feed = _board(
        task("TASK-1", "Done", settled="archived", settled_at=5.0),
        task("TASK-2", "Waiting", dependencies=("TASK-1",)),
    )

    assert _release(feed, store) == []


def _pinned(*extra: Any, references: tuple[str, ...] = (CHILD_PR,)) -> BoardFeed:
    return _board(
        task("TASK-1", "Done", references=references),
        task("TASK-2", "Waiting", dependencies=("TASK-1",)),
        *extra,
    )


def test_without_a_settle_rule_a_pinned_dependency_settles_on_done_alone(store: PullStore) -> None:
    store.save([_pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=WHEN)])

    assert _release(_pinned(), store) == ["TASK-2"]


def test_a_pin_settled_dependency_waits_for_its_bump_merge(store: PullStore) -> None:
    store.save([_pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=WHEN)])
    feed = _pinned()

    assert _release(feed, store, "pin-bump") == []

    store.save([_pull("acme/trantor", 50, state="MERGED", sha=PARENT, at=LATER, files=["starpulse"])])

    assert _release(feed, store, "pin-bump") == ["TASK-2"]


def test_a_bump_merged_before_the_child_does_not_settle_it(store: PullStore) -> None:
    store.save(
        [
            _pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=LATER),
            _pull("acme/trantor", 50, state="MERGED", sha=PARENT, at=WHEN, files=["starpulse"]),
        ]
    )

    assert _release(_pinned(), store, "pin-bump") == []


def test_a_merge_that_does_not_move_the_pin_does_not_settle_the_dependency(store: PullStore) -> None:
    store.save(
        [
            _pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=WHEN),
            _pull("acme/trantor", 50, state="MERGED", sha=PARENT, at=LATER, files=["README.md"]),
        ]
    )

    assert _release(_pinned(), store, "pin-bump") == []


def test_a_pinned_pull_request_the_store_lacks_or_holds_open_holds_the_dependent(store: PullStore) -> None:
    feed = _pinned()
    assert _release(feed, store, "pin-bump") == []

    store.save([_pull("acme/starpulse", 10, state="OPEN", sha=None, at=None)])

    assert _release(feed, store, "pin-bump") == []


def test_a_closed_pinned_pull_request_never_reaches_the_pin_and_is_ignored(store: PullStore) -> None:
    store.save([_pull("acme/starpulse", 10, state="CLOSED", sha=None, at=None)])

    assert _release(_pinned(), store, "pin-bump") == ["TASK-2"]


def test_a_dependency_citing_an_unpinned_repository_settles_on_done_alone(store: PullStore) -> None:
    assert _release(_pinned(references=(OTHER_PR,)), store, "pin-bump") == ["TASK-2"]


def test_a_completed_dependency_still_holds_its_dependent_until_its_bump_merges(store: PullStore) -> None:
    store.save([_pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=WHEN)])
    feed = _board(
        task("TASK-1", "Done", references=(CHILD_PR,), settled="completed", settled_at=5.0),
        task("TASK-2", "Waiting", dependencies=("TASK-1",)),
    )

    assert _release(feed, store, "pin-bump") == []


def test_a_released_task_the_board_has_not_read_back_is_not_written_twice(store: PullStore) -> None:
    feed = _board(task("TASK-1", "Done"), task("TASK-2", "Waiting", dependencies=("TASK-1",)))
    edits = Edits()
    releaser = Releaser(feed, store, edits)

    assert releaser.release() == ["TASK-2"]
    assert releaser.release() == []
    assert len(edits.calls) == 1

    feed.put(task("TASK-2", "Ready", dependencies=("TASK-1",)))
    assert releaser.release() == []
    feed.put(task("TASK-2", "Waiting", dependencies=("TASK-1",)))

    assert releaser.release() == ["TASK-2"]


def test_a_refused_move_is_tried_again_on_the_next_pass(store: PullStore) -> None:
    feed = _board(task("TASK-1", "Done"), task("TASK-2", "Waiting", dependencies=("TASK-1",)))
    answers = iter([Written(False, "refused by the board"), Written(True, "")])
    calls: list[str] = []

    def edit(name: str, changes: Mapping[str, Any], comment: str | Sequence[str], /) -> Written:
        calls.append(name)
        return next(answers)

    releaser = Releaser(feed, store, edit)

    assert releaser.release() == []
    assert releaser.release() == ["TASK-2"]
    assert calls == ["TASK-2", "TASK-2"]
