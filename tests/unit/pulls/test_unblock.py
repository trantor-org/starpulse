"""A Waiting task moves to Ready once every dependency merges; a pinned repository's dependency merges on its bump."""

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Written
from starpulse.pulls.adapters.inbound.unblock import Unblocker
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.pulls.model.pins import LiveBuild, Repo
from starpulse.runtime.adapter_kit import task

from tests.machines import ROLES

CHILD, PARENT = "c" * 40, "p" * 40
CHILD_PR = "https://github.com/acme/starpulse/pull/10"
OTHER_PR = "https://github.com/acme/widgets/pull/7"
REPOS = [Repo(name="starpulse", path="starpulse", applied_by="pin-bump")]
WHEN = "2026-10-06T21:14:09Z"
LATER = "2026-10-07T09:00:00Z"
NEEDS_CRITERIA = (
    "## Start Criteria\n```yaml\nstart_criteria:\n  - id: soak\n    kind: prom\n    expr: up\n    equals: 1\n```\n"
)


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
    """The parent's pointer reads: `main`'s bump PR pins `CHILD` at `starpulse`; a child contains a commit it equals.
    `tip` is the parent's default-branch commit, None when unreadable."""

    def __init__(self, tip: str | None = None) -> None:
        self.tip = tip

    def head(self, repo: str) -> str | None:
        return self.tip if repo == "acme/trantor" else None

    def pointer(self, repo: str, sha: str, path: str) -> str | None:
        return CHILD if (repo, sha, path) == ("acme/trantor", PARENT, "starpulse") else None

    def reaches(self, repo: str, sha: str, pointer: str) -> bool:
        return sha == pointer


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


def _pull(repo: str, number: int, *, state: str, sha: str | None, at: str | None, files: Sequence[str] = (), branch: str = "") -> dict:
    return {
        "repo": repo,
        "number": number,
        "state": state,
        "isDraft": False,
        "mergeable": "UNKNOWN",
        "baseRefName": "main",
        "headRefOid": f"{number:040x}",
        "headRefName": branch,
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
    feed = BoardFeed(roles=ROLES)
    for each in tasks:
        feed.put(each)
    return feed


def _unblock(feed: BoardFeed, store: PullStore, pin_rule: str | None = None, pins: Pins | None = None) -> list[str]:
    edits = Edits()
    Unblocker(feed, store, edits, repos=REPOS, pin_rule=pin_rule, pins=pins or Pins()).unblock()
    return edits.moved


def test_a_waiting_task_whose_dependencies_are_all_done_moves_to_ready(store: PullStore) -> None:
    feed = _board(
        task("TASK-1", "Done"),
        task("TASK-2", "Done"),
        task("TASK-3", "Waiting", dependencies=("TASK-1", "TASK-2")),
    )
    edits = Edits()

    moved = Unblocker(feed, store, edits).unblock()

    assert moved == ["TASK-3"]
    assert [(name, changes) for name, changes, _ in edits.calls] == [("TASK-3", {"status": "ready"})]


def test_a_task_with_an_open_dependency_stays_waiting(store: PullStore) -> None:
    feed = _board(
        task("TASK-1", "Done"),
        task("TASK-2", "In Progress"),
        task("TASK-3", "Waiting", dependencies=("TASK-1", "TASK-2")),
    )

    assert _unblock(feed, store) == []


def test_a_board_with_no_dependencies_has_nothing_to_unblock(store: PullStore) -> None:
    feed = _board(task("TASK-1", "Waiting"), task("TASK-2", "Ready"), task("TASK-3", "Done"))

    assert _unblock(feed, store) == []


def test_only_waiting_tasks_are_unblocked(store: PullStore) -> None:
    feed = _board(
        task("TASK-1", "Done"),
        task("TASK-2", "In Progress", dependencies=("TASK-1",)),
        task("TASK-3", "Review", dependencies=("TASK-1",)),
    )

    assert _unblock(feed, store) == []


def test_a_task_gated_by_start_criteria_is_left_to_them(store: PullStore) -> None:
    feed = _board(
        task("TASK-1", "Done"),
        task("TASK-2", "Waiting", dependencies=("TASK-1",), description=NEEDS_CRITERIA),
    )

    assert _unblock(feed, store) == []


def test_a_completed_dependency_is_done(store: PullStore) -> None:
    feed = _board(
        task("TASK-1", "Done", settled="completed", settled_at=5.0),
        task("TASK-2", "Waiting", dependencies=("TASK-1",)),
    )

    assert _unblock(feed, store) == ["TASK-2"]


def test_an_archived_dependency_never_unblocks_its_dependent(store: PullStore) -> None:
    feed = _board(
        task("TASK-1", "Done", settled="archived", settled_at=5.0),
        task("TASK-2", "Waiting", dependencies=("TASK-1",)),
    )

    assert _unblock(feed, store) == []


def _pinned(*extra: Any, references: tuple[str, ...] = (CHILD_PR,)) -> BoardFeed:
    return _board(
        task("TASK-1", "Done", references=references),
        task("TASK-2", "Waiting", dependencies=("TASK-1",)),
        *extra,
    )


def test_without_a_merge_rule_a_pinned_dependency_merges_on_done_alone(store: PullStore) -> None:
    store.save([_pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=WHEN)])

    assert _unblock(_pinned(), store) == ["TASK-2"]


def test_a_pin_merged_dependency_waits_for_its_bump_merge(store: PullStore) -> None:
    store.save([_pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=WHEN)])
    feed = _pinned()

    assert _unblock(feed, store, "pin-bump") == []

    store.save([_pull("acme/trantor", 50, state="MERGED", sha=PARENT, at=LATER, files=["starpulse"])])

    assert _unblock(feed, store, "pin-bump") == ["TASK-2"]


def test_a_pull_request_a_dependency_cites_for_another_task_never_holds_its_dependent(store: PullStore) -> None:
    dependents_pr = "https://github.com/acme/starpulse/pull/11"
    store.save(
        [
            _pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=WHEN, branch="claude/task-1-the-change"),
            _pull("acme/starpulse", 11, state="OPEN", sha=None, at=None, branch="claude/task-2-the-dependents-change"),
            _pull("acme/trantor", 50, state="MERGED", sha=PARENT, at=LATER, files=["starpulse"]),
        ]
    )

    assert _unblock(_pinned(references=(CHILD_PR, dependents_pr)), store, "pin-bump") == ["TASK-2"]


def test_an_unblock_pass_after_a_restart_reads_no_pin_answer_the_board_saved(
    store: PullStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def gh(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        asked.append(command[2])
        return subprocess.CompletedProcess(command, 1, "", "")

    monkeypatch.setattr(subprocess, "run", gh)
    store.save([_pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=WHEN)])
    store.save([_pull("acme/trantor", 50, state="MERGED", sha=PARENT, at=LATER, files=["starpulse"])])
    feed = _pinned()
    saved = {
        "pointers": [["acme/trantor", PARENT, "starpulse", CHILD]],
        "reaches": [["acme/starpulse", CHILD, CHILD, True]],
    }
    feed.set_pulls({}, {"pins": saved})  # what `BoardFeed.resume` restores
    edits = Edits()

    Unblocker(feed, store, edits, repos=REPOS, pin_rule="pin-bump").unblock()

    assert asked == []
    assert edits.moved == ["TASK-2"]


def test_a_pin_pushed_to_the_parent_default_branch_without_a_pull_request_merges_the_dependency(
    store: PullStore,
) -> None:
    store.save(
        [
            _pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=WHEN),
            _pull("acme/trantor", 50, state="MERGED", sha="d" * 40, at=LATER, files=["README.md"]),
        ]
    )

    assert _unblock(_pinned(), store, "pin-bump", Pins(tip=PARENT)) == ["TASK-2"]


def test_a_parent_default_branch_that_does_not_pin_the_merge_holds_the_dependent(store: PullStore) -> None:
    store.save(
        [
            _pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=WHEN),
            _pull("acme/trantor", 50, state="MERGED", sha="d" * 40, at=LATER, files=["README.md"]),
        ]
    )

    assert _unblock(_pinned(), store, "pin-bump", Pins(tip="d" * 40)) == []


def test_a_bump_merged_before_the_child_does_not_merge_it(store: PullStore) -> None:
    store.save(
        [
            _pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=LATER),
            _pull("acme/trantor", 50, state="MERGED", sha=PARENT, at=WHEN, files=["starpulse"]),
        ]
    )

    assert _unblock(_pinned(), store, "pin-bump") == []


def test_a_merge_that_does_not_move_the_pin_does_not_merge_the_dependency(store: PullStore) -> None:
    store.save(
        [
            _pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=WHEN),
            _pull("acme/trantor", 50, state="MERGED", sha=PARENT, at=LATER, files=["README.md"]),
        ]
    )

    assert _unblock(_pinned(), store, "pin-bump") == []


def test_a_pinned_pull_request_the_store_lacks_or_holds_open_holds_the_dependent(store: PullStore) -> None:
    feed = _pinned()
    assert _unblock(feed, store, "pin-bump") == []

    store.save([_pull("acme/starpulse", 10, state="OPEN", sha=None, at=None)])

    assert _unblock(feed, store, "pin-bump") == []


def test_a_closed_pinned_pull_request_never_reaches_the_pin_and_is_ignored(store: PullStore) -> None:
    store.save([_pull("acme/starpulse", 10, state="CLOSED", sha=None, at=None)])

    assert _unblock(_pinned(), store, "pin-bump") == ["TASK-2"]


def test_a_dependency_citing_an_unpinned_repository_merges_on_done_alone(store: PullStore) -> None:
    assert _unblock(_pinned(references=(OTHER_PR,)), store, "pin-bump") == ["TASK-2"]


def test_a_completed_dependency_still_holds_its_dependent_until_its_bump_merges(store: PullStore) -> None:
    store.save([_pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=WHEN)])
    feed = _board(
        task("TASK-1", "Done", references=(CHILD_PR,), settled="completed", settled_at=5.0),
        task("TASK-2", "Waiting", dependencies=("TASK-1",)),
    )

    assert _unblock(feed, store, "pin-bump") == []


def test_a_unblocked_task_the_board_has_not_read_back_is_not_written_twice(store: PullStore) -> None:
    feed = _board(task("TASK-1", "Done"), task("TASK-2", "Waiting", dependencies=("TASK-1",)))
    edits = Edits()
    unblocker = Unblocker(feed, store, edits)

    assert unblocker.unblock() == ["TASK-2"]
    assert unblocker.unblock() == []
    assert len(edits.calls) == 1

    feed.put(task("TASK-2", "Ready", dependencies=("TASK-1",)))
    assert unblocker.unblock() == []
    feed.put(task("TASK-2", "Waiting", dependencies=("TASK-1",)))

    assert unblocker.unblock() == ["TASK-2"]


def test_a_refused_move_is_tried_again_on_the_next_pass(store: PullStore) -> None:
    feed = _board(task("TASK-1", "Done"), task("TASK-2", "Waiting", dependencies=("TASK-1",)))
    answers = iter([Written(False, "refused by the board"), Written(True, "")])
    calls: list[str] = []

    def edit(name: str, changes: Mapping[str, Any], comment: str | Sequence[str], /) -> Written:
        calls.append(name)
        return next(answers)

    unblocker = Unblocker(feed, store, edit)

    assert unblocker.unblock() == []
    assert unblocker.unblock() == ["TASK-2"]
    assert calls == ["TASK-2", "TASK-2"]


def _live(feed: BoardFeed, store: PullStore, commit: str | None) -> list[str]:
    edits = Edits()
    Unblocker(feed, store, edits, pins=Pins(), live=LiveBuild("starpulse", lambda: commit)).unblock()
    return edits.moved


def _merged_child(store: PullStore) -> None:
    store.save([_pull("acme/starpulse", 10, state="MERGED", sha=CHILD, at=WHEN)])


def test_a_merge_the_running_build_contains_settles_its_dependency(store: PullStore) -> None:
    _merged_child(store)

    assert _live(_pinned(), store, CHILD) == ["TASK-2"]


def test_a_merge_the_running_build_lacks_holds_its_dependent(store: PullStore) -> None:
    _merged_child(store)

    assert _live(_pinned(), store, "d" * 40) == []


def test_a_build_with_no_commit_holds_the_dependent(store: PullStore) -> None:
    _merged_child(store)

    assert _live(_pinned(), store, None) == []


def test_a_release_pull_request_the_store_lacks_or_holds_open_holds_the_dependent(store: PullStore) -> None:
    assert _live(_pinned(), store, CHILD) == []

    store.save([_pull("acme/starpulse", 10, state="OPEN", sha=None, at=None)])

    assert _live(_pinned(), store, CHILD) == []


def test_a_closed_release_pull_request_is_ignored(store: PullStore) -> None:
    store.save([_pull("acme/starpulse", 10, state="CLOSED", sha=None, at=None)])

    assert _live(_pinned(), store, None) == ["TASK-2"]


def test_a_dependency_in_another_repository_settles_on_done_alone_under_the_release_rule(store: PullStore) -> None:
    assert _live(_pinned(references=(OTHER_PR,)), store, None) == ["TASK-2"]
