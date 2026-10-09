"""Each task's pull requests as the snapshot carries them: projected from the PR store, never read from GitHub."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.ci.ci_trail import parse
from starpulse._internal.config.config import Repo
from starpulse._internal.config.pins import GitHub
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.pulls.pull_requests import STALE_S, GhUnavailableError, PullRequests, query_github
from starpulse._internal.pulls.pulls import PullStore

REPO = "https://github.com/acme/widgets/pull"
FIRST, SECOND = f"{REPO}/1750", f"{REPO}/1751"
SHA, MERGED_AT = "9f2c1ab07d3e4f5a6b7c8d9e0f1a2b3c4d5e6f70", "2026-10-06T21:14:09Z"
OPENED_AT = "2026-10-06T20:00:00Z"
NOW = 10_000.0


@pytest.fixture(autouse=True)
def no_github(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every `gh` call in this module's tests is a failure unless the test installs its own."""

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"GitHub was read: {command}")

    monkeypatch.setattr(subprocess, "run", run)


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


def _ci(*, mergeable: str = "MERGEABLE", suites: tuple[dict, ...] = (), merged_at: str | None = None) -> dict:
    """The parts of a GraphQL `pullRequest` node the store keeps for `ci_trail.parse`."""
    return {
        "createdAt": OPENED_AT,
        "mergeable": mergeable,
        "merged": merged_at is not None,
        "mergedAt": merged_at,
        "commits": {"nodes": [{"commit": {"oid": "abc123", "checkSuites": {"nodes": suites}}}]},
        "timelineItems": {"nodes": []},
    }


def _stored(
    number: int,
    checks: str = "pass",
    *,
    state: str = "OPEN",
    threads: int = 0,
    fetched: float = NOW,
    merge_sha: str | None = None,
    merged_at: str | None = None,
    files: tuple[str, ...] = (),
    behind: int | None = None,
    ci: dict | None = None,
    repo: str = "acme/widgets",
) -> dict:
    """A record as the PR store holds it, with the detail the per-task state reads."""
    return {
        "repo": repo,
        "number": number,
        "state": state,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefOid": f"{number:040x}",
        "body": "",
        "checks": checks,
        "requiredChecks": [],
        "threads": threads,
        "updatedAt": "2026-10-06T20:00:00Z",
        "fetchedAt": fetched,
        "detail": {
            "mergedAt": merged_at,
            "mergeSha": merge_sha,
            "behindMain": behind,
            "files": list(files),
            "ci": ci or _ci(merged_at=merged_at),
        },
    }


def _record(
    number: int,
    checks: str,
    *,
    merged: bool = False,
    threads: int = 0,
    stale: bool = False,
    merge_sha: str | None = None,
    merged_at: str | None = None,
    files: list[str] | None = None,
    behind_main: int | None = None,
    repo: str = "acme/widgets",
) -> dict:
    """The per-task record the feed carries."""
    return {
        "number": number,
        "url": f"https://github.com/{repo}/pull/{number}",
        "checks": checks,
        "merged": merged,
        "merge_sha": merge_sha,
        "merged_at": merged_at,
        "files": files or [],
        "threads": threads,
        "behind_main": behind_main,
        "stale": stale,
    }


def _feed(**tasks: list[str]) -> BoardFeed:
    feed = BoardFeed()
    for name, prs in tasks.items():
        feed.put(task(name.upper().replace("_", "-"), "In Progress", references=prs))
    return feed


def _drawn(pulls: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """`pulls` as the page is sent them: without the `files` a record keeps for the feed's own reads."""
    return {task: [{k: v for k, v in pull.items() if k != "files"} for pull in found] for task, found in pulls.items()}


def _pulls(feed: BoardFeed) -> dict:
    return feed.snapshot()["pulls"]


def _records(feed: BoardFeed) -> dict[str, dict]:
    """The records by URL the projector last handed the feed, `files` and `applied_by` included."""
    return feed.pull_answers()["records"]


def test_the_snapshot_carries_each_tasks_pr_number_check_rollup_merged_state_and_open_thread_count(
    store: PullStore,
) -> None:
    store.save([_stored(1750, "failing", threads=2), _stored(1751, "pass", state="MERGED")])
    feed = _feed(proj_7=[FIRST], proj_8=[SECOND])

    PullRequests(feed, store, clock=lambda: NOW).refresh()

    assert _pulls(feed) == _drawn(
        {"PROJ-7": [_record(1750, "failing", threads=2)], "PROJ-8": [_record(1751, "pass", merged=True)]}
    )


def test_a_record_carries_the_merge_commit_and_time_the_changed_files_and_the_commits_behind_main(
    store: PullStore,
) -> None:
    store.save(
        [
            _stored(1750, state="MERGED", merge_sha=SHA, merged_at=MERGED_AT, files=("a.py", "b.py")),
            _stored(1751, behind=4),
        ]
    )
    feed = _feed(proj_7=[FIRST, SECOND])

    PullRequests(feed, store, clock=lambda: NOW).refresh()

    assert _records(feed) == {
        FIRST: _record(1750, "pass", merged=True, merge_sha=SHA, merged_at=MERGED_AT, files=["a.py", "b.py"]),
        SECOND: _record(1751, "pass", behind_main=4),
    }


def test_a_task_with_several_prs_carries_them_in_the_order_it_cites_them(store: PullStore) -> None:
    store.save([_stored(1750), _stored(1751, "pending")])
    feed = _feed(proj_7=[SECOND, FIRST])

    PullRequests(feed, store, clock=lambda: NOW).refresh()

    assert [pr["number"] for pr in _pulls(feed)["PROJ-7"]] == [1751, 1750]


def test_a_task_with_no_pr_and_a_settled_tasks_pr_are_not_in_the_map(store: PullStore) -> None:
    store.save([_stored(1750)])
    feed = _feed(proj_7=[])
    feed.put(task("PROJ-8", "Done", settled="completed", references=[FIRST]))

    PullRequests(feed, store, clock=lambda: NOW).refresh()

    assert _pulls(feed) == {}


def test_a_pr_the_store_does_not_hold_is_left_out_beside_the_ones_it_does(store: PullStore) -> None:
    store.save([_stored(1750)])
    feed = _feed(proj_7=[FIRST, SECOND])

    PullRequests(feed, store, clock=lambda: NOW).refresh()

    assert [pr["number"] for pr in _pulls(feed)["PROJ-7"]] == [1750]


def test_a_pr_the_store_holds_without_detail_is_left_out_until_the_store_reads_it(store: PullStore) -> None:
    store.save([{**_stored(1750), "detail": None}])
    feed = _feed(proj_7=[FIRST])

    PullRequests(feed, store, clock=lambda: NOW).refresh()

    assert _pulls(feed) == {}


def test_an_open_pr_the_store_last_read_over_the_stale_age_ago_is_marked_stale_and_a_merged_one_is_not(
    store: PullStore,
) -> None:
    old = NOW - STALE_S - 1
    store.save([_stored(1750, fetched=old), _stored(1751, state="MERGED", fetched=old)])
    feed = _feed(proj_7=[FIRST, SECOND])

    PullRequests(feed, store, clock=lambda: NOW).refresh()

    assert [pr["stale"] for pr in _pulls(feed)["PROJ-7"]] == [True, False]


def test_the_next_read_of_the_store_clears_the_stale_marker_and_takes_the_new_value(store: PullStore) -> None:
    store.save([_stored(1750, "pending", fetched=NOW - STALE_S - 1)])
    feed = _feed(proj_7=[FIRST])
    source = PullRequests(feed, store, clock=lambda: NOW)
    source.refresh()

    store.save([_stored(1750, "pass")])
    source.refresh()

    assert _pulls(feed) == _drawn({"PROJ-7": [_record(1750, "pass")]})


def test_a_pr_the_task_no_longer_cites_leaves_the_map_on_the_next_refresh(store: PullStore) -> None:
    store.save([_stored(1750), _stored(1751)])
    feed = _feed(proj_7=[FIRST, SECOND])
    source = PullRequests(feed, store, clock=lambda: NOW)
    source.refresh()

    feed.put(task("PROJ-7", "In Progress", references=[SECOND]))
    source.refresh()

    assert [pr["number"] for pr in _pulls(feed)["PROJ-7"]] == [1751]


def test_a_change_is_published_to_subscribers_and_an_unchanged_refresh_is_not(store: PullStore) -> None:
    store.save([_stored(1750, "pending")])
    feed = _feed(proj_7=[FIRST])
    _, changes = feed.subscribe()
    source = PullRequests(feed, store, clock=lambda: NOW)

    source.refresh()
    source.refresh()
    store.save([_stored(1750, "pass")])
    source.refresh()

    assert [changes.get_nowait() for _ in range(changes.qsize())] == [
        ("pulls", {"pulls": _drawn({"PROJ-7": [_record(1750, "pending")]})}),
        ("pulls", {"pulls": _drawn({"PROJ-7": [_record(1750, "pass")]})}),
    ]


class _Trail:
    """Stands in for `CiTrail`: keeps what a refresh handed it."""

    def __init__(self) -> None:
        self.recorded: list[dict] = []

    def record(self, pulls: dict) -> None:
        self.recorded.append(pulls)


def test_a_refresh_hands_each_tasks_ci_histories_from_the_stored_detail_to_the_ci_trail(store: PullStore) -> None:
    suite = {
        "status": "COMPLETED",
        "conclusion": "FAILURE",
        "createdAt": "2026-10-06T20:01:00Z",
        "updatedAt": "2026-10-06T20:05:00Z",
        "workflowRun": {"runAttempt": 2},
    }
    store.save([_stored(1750, ci=_ci(mergeable="CONFLICTING", suites=(suite,))), _stored(1751)])
    trail = _Trail()

    PullRequests(_feed(proj_7=[FIRST, SECOND]), store, trail=trail, clock=lambda: NOW).refresh()

    (recorded,) = trail.recorded
    first, second = recorded["PROJ-7"]
    assert first == parse(FIRST, _ci(mergeable="CONFLICTING", suites=(suite,)))
    assert (first.opened, first.conflicting, first.merged_at) == (
        datetime(2026, 10, 6, 20, 0, tzinfo=UTC).timestamp(),
        True,
        None,
    )
    assert (first.heads[0].suites[0].attempt, first.heads[0].suites[0].conclusion) == (2, "FAILURE")
    assert second.url == SECOND


def test_a_task_citing_a_pr_the_store_does_not_hold_hands_the_ci_trail_nothing_for_it(store: PullStore) -> None:
    trail = _Trail()

    PullRequests(_feed(proj_7=[FIRST]), store, trail=trail, clock=lambda: NOW).refresh()

    assert trail.recorded == [{"PROJ-7": []}]


class _Pins:
    """Stands in for the pin reads: the widgets merge pins POINTER, which contains the skills merge."""

    def pointer(self, repo: str, sha: str, path: str) -> str | None:
        return "pointer" if (repo, sha, path) == ("acme/widgets", SHA, "skills") else None

    def reaches(self, repo: str, sha: str, pointer: str) -> bool:
        return (repo, sha, pointer) == ("acme/skills", "5" * 40, "pointer")


CHILD = "https://github.com/acme/skills/pull/7"
REPOS = (Repo(name="skills", path="skills", applied_by="pin-bump"),)


def _pinned(store: PullStore) -> BoardFeed:
    store.save(
        [
            _stored(1750, state="MERGED", merge_sha=SHA, merged_at=MERGED_AT),
            _stored(7, state="MERGED", merge_sha="5" * 40, merged_at="2026-10-06T20:00:00Z", repo="acme/skills"),
        ]
    )
    return _feed(proj_7=[FIRST], proj_8=[CHILD])


def test_a_merged_pr_of_a_pinned_repository_carries_the_parent_merge_that_applies_it(store: PullStore) -> None:
    feed = _pinned(store)

    PullRequests(feed, store, repos=REPOS, pins=_Pins(), clock=lambda: NOW).refresh()

    assert _records(feed)[CHILD]["applied_by"] == SHA
    assert "applied_by" not in _records(feed)[FIRST]


def test_pin_answers_saved_with_the_board_spare_a_restarted_projector_every_pointer_and_compare_read(
    store: PullStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def gh(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        asked.append(command[2])
        return subprocess.CompletedProcess(command, 0, SHA if "/contents/" in command[2] else "ahead", "")

    monkeypatch.setattr(subprocess, "run", gh)
    before = _pinned(store)
    PullRequests(before, store, repos=REPOS, pins=GitHub(), clock=lambda: NOW).refresh()
    assert len(asked) == 2

    after = _feed(proj_7=[FIRST], proj_8=[CHILD])
    after.set_pulls({}, before.pull_answers())  # what `BoardFeed.resume` restores
    asked.clear()
    PullRequests(after, store, repos=REPOS, pins=GitHub(), clock=lambda: NOW).refresh()

    assert asked == []
    assert _records(after)[CHILD]["applied_by"] == SHA


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (FileNotFoundError("gh is not installed"), "gh is not installed"),
        (subprocess.TimeoutExpired("gh api", 30), "timed out after 30 seconds"),
    ],
)
def test_a_missing_or_hung_gh_is_a_failed_query_naming_why(
    monkeypatch: pytest.MonkeyPatch, error: Exception, message: str
) -> None:
    def run(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(GhUnavailableError, match=message):
        query_github("acme/widgets", "query")


@pytest.mark.parametrize(
    ("stdout", "stderr", "code", "message"),
    [
        ("", "gh: not logged in", 1, "gh: not logged in"),
        ("", "", 4, "gh exited 4"),
        ("not json", "", 0, "gh exited 0"),
        ('{"data": {"repository": null}}', "", 0, "acme/widgets is not readable"),
    ],
)
def test_gh_failures_are_a_failed_query_naming_why(
    monkeypatch: pytest.MonkeyPatch, stdout: str, stderr: str, code: int, message: str
) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda command, **_: subprocess.CompletedProcess(command, code, stdout, stderr)
    )

    with pytest.raises(GhUnavailableError, match=message):
        query_github("acme/widgets", "query")


def test_gh_exiting_non_zero_for_one_missing_pr_still_yields_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    out = '{"data": {"repository": {"p1": {"number": 1}, "p2": null}}}'
    monkeypatch.setattr(subprocess, "run", lambda command, **_: subprocess.CompletedProcess(command, 1, out, "x"))

    assert query_github("acme/widgets", "query") == {"p1": {"number": 1}, "p2": None}
