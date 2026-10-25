"""The PR store: every open and recently updated pull request of a repository, read in one query and served."""

import json
import logging
import re
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event

from starpulse._internal.config.config import Repo
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import task
from starpulse.pulls.pull_requests import query_github
from starpulse.pulls.pull_store import PullSync, refresh_pull
from starpulse.pulls.pulls import PullStore

REPO = "acme/widgets"
OLD, NEW = "2026-10-07T12:00:00Z", "2026-10-07T13:00:00Z"
_PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}
SUITE = {
    "status": "COMPLETED",
    "conclusion": "SUCCESS",
    "createdAt": OLD,
    "updatedAt": NEW,
    "workflowRun": {"runAttempt": 1},
}


class Github:
    """One repository on GitHub, answering the store's queries from `pulls` and recording each one it is asked."""

    def __init__(self) -> None:
        self.pulls: dict[int, dict] = {}
        self.queries: list[str] = []

    def add(
        self,
        number: int,
        *,
        state: str = "OPEN",
        updated: str = OLD,
        body: str = "",
        checks: dict[str, str] | None = None,
        threads: tuple[bool, ...] = (),
        merged_at: str | None = None,
        files: tuple[str, ...] = (),
        behind: int | None = None,
        branch: str = "claude/task-7-thing",
        author: str | None = "coderabbitai",
    ) -> None:
        """A PR; `checks` maps each required check to its conclusion, or to IN_PROGRESS while it runs. Each of its
        `threads` (resolved or not) opens with a comment by `author`, None for a deleted account."""
        self.pulls[number] = {
            "state": state,
            "updated": updated,
            "body": body,
            "checks": checks or {},
            "threads": threads,
            "merged_at": merged_at,
            "files": files,
            "behind": behind,
            "branch": branch,
            "author": author,
        }

    def _node(self, number: int) -> dict:
        pull = self.pulls[number]
        contexts = [
            {
                "__typename": "CheckRun",
                "name": name,
                "status": "IN_PROGRESS" if result == "IN_PROGRESS" else "COMPLETED",
                "conclusion": None if result == "IN_PROGRESS" else result,
                "isRequired": True,
            }
            for name, result in pull["checks"].items()
        ]
        return {
            "number": number,
            "state": pull["state"],
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "baseRefName": "main",
            "headRefName": pull["branch"],
            "headRefOid": f"{number:040x}",
            "body": pull["body"],
            "updatedAt": pull["updated"],
            "createdAt": OLD,
            "mergedAt": pull["merged_at"],
            "mergeCommit": {"oid": f"{number:040x}"[::-1]} if pull["state"] == "MERGED" else None,
            "files": {"nodes": [{"path": path} for path in pull["files"]]},
            "headRef": None if pull["behind"] is None else {"compare": {"aheadBy": pull["behind"]}},
            "commits": {"nodes": [{"commit": {"statusCheckRollup": {"contexts": {"nodes": contexts}}}}]},
            "ciCommits": {"nodes": [{"commit": {"oid": f"{number:040x}", "checkSuites": {"nodes": [SUITE]}}}]},
            "timelineItems": {"nodes": []},
            "reviewThreads": {
                "nodes": [
                    {
                        "id": f"PRRT_{number}_{index}",
                        "isResolved": resolved,
                        "comments": {"nodes": [{"author": {"login": pull["author"]} if pull["author"] else None}]},
                    }
                    for index, resolved in enumerate(pull["threads"])
                ]
            },
        }

    def __call__(self, repo: str, query: str) -> dict:
        assert repo == REPO
        self.queries.append(query)
        answer: dict = {}
        for number in re.findall(r"p(\d+): pullRequest", query):
            answer[f"p{number}"] = self._node(int(number)) if int(number) in self.pulls else None
        return answer


def _stored(repo: str, number: int) -> dict:
    return {
        "repo": repo,
        "number": number,
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefOid": f"{number:040x}",
        "body": "",
        "checks": "none",
        "requiredChecks": [],
        "threads": 0,
        "updatedAt": OLD,
        "mergedAt": None,
        "mergeSha": None,
        "fetchedAt": 1.0,
    }


def _read(store: PullStore, github: Github, now: float, *numbers: int) -> None:
    """Read each of `numbers` (every PR `github` holds when none are named) as a refresh request does."""
    for number in numbers or tuple(github.pulls):
        refresh_pull(REPO, number, store, now, github)


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


def test_a_record_names_each_unresolved_thread_by_id_and_first_comment_author_and_the_head_branch(
    store: PullStore,
) -> None:
    github = Github()
    github.add(1, threads=(False, True, False), author="adinballew", branch="claude/task-4087-serve")

    _read(store, github, 100.0)

    [pull] = store.find()
    assert pull["unresolvedThreads"] == [
        {"id": "PRRT_1_0", "author": "adinballew"},
        {"id": "PRRT_1_2", "author": "adinballew"},
    ]
    assert pull["threads"] == 2
    assert pull["headRefName"] == "claude/task-4087-serve"
    asked = " ".join(github.queries)
    assert "headRefName" in asked and "comments(first: 1)" in asked


def test_a_thread_whose_first_comment_has_no_author_is_recorded_with_a_null_author(store: PullStore) -> None:
    github = Github()
    github.add(1, threads=(False,), author=None)

    _read(store, github, 100.0)

    assert [pull["unresolvedThreads"] for pull in store.find()] == [[{"id": "PRRT_1_0", "author": None}]]


def test_a_record_saved_without_threads_or_branch_is_served_with_both_null(store: PullStore) -> None:
    """A record an older refresh wrote: a reader must see it cannot name the threads, not that it has none."""
    store.save([_stored(REPO, 1)])

    [pull] = store.find()
    assert (pull["unresolvedThreads"], pull["headRefName"]) == (None, None)


def test_a_read_runs_no_sql_because_a_row_step_gives_up_the_gil_and_waits_behind_every_busy_thread(
    store: PullStore,
) -> None:
    """A 1,968-row read made 1,968 such steps and took 12-45 s beside a busy thread (TASK-5076), so reads are served
    from memory: the open and recently saved records (the rest are read when asked for, `test_pull_store_window`)."""
    store.save([{**_stored(REPO, 1), "detail": {"files": ["a.py"]}}, _stored(REPO, 2) | {"state": "MERGED"}])
    statements: list[str] = []
    event.listen(store._engine, "before_cursor_execute", lambda *args: statements.append(args[2]))

    open_ones = store.find(state="OPEN")
    merged = store.find(REPO, 2)
    one = store.find(REPO, 1, "OPEN", detailed=True)

    assert (len(open_ones), len(merged), one[0]["detail"], statements) == (1, 1, {"files": ["a.py"]}, [])


def test_a_store_opened_over_saved_rows_serves_what_the_first_one_did(store: PullStore) -> None:
    store.save([{**_stored(REPO, 2), "detail": {"files": ["b.py"]}, "threads": 3}, _stored(REPO, 1)])

    assert PullStore(store._engine).find(detailed=True) == store.find(detailed=True)


def test_a_required_check_turning_red_with_updated_at_unchanged_reaches_the_store_on_the_next_read(
    store: PullStore,
) -> None:
    github = Github()
    github.add(1, checks={"lint": "IN_PROGRESS", "test": "SUCCESS"})
    _read(store, github, 100.0)
    (before,) = store.find(number=1)

    github.add(
        1, checks={"lint": "FAILURE", "test": "SUCCESS"}
    )  # updatedAt stays OLD: a check finishing does not bump it
    _read(store, github, 160.0)
    (after,) = store.find(number=1)

    assert (before["checks"], before["updatedAt"]) == ("pending", OLD)
    assert (after["checks"], after["updatedAt"], after["fetchedAt"]) == ("failing", OLD, 160.0)
    assert after["requiredChecks"] == [{"name": "lint", "result": "failing"}, {"name": "test", "result": "pass"}]


def test_a_record_carries_the_facts_pr_status_prints(store: PullStore) -> None:
    github = Github()
    github.add(4, checks={"lint": "SUCCESS"}, threads=(True, False, False))

    _read(store, github, 100.0)

    assert store.find(number=4) == [
        {
            "repo": REPO,
            "number": 4,
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "baseRefName": "main",
            "headRefOid": f"{4:040x}",
            "body": "",
            "checks": "pass",
            "requiredChecks": [{"name": "lint", "result": "pass"}],
            "threads": 2,
            "unresolvedThreads": [{"id": f"PRRT_4_{index}", "author": "coderabbitai"} for index in (1, 2)],
            "headRefName": "claude/task-7-thing",
            "updatedAt": OLD,
            "mergedAt": None,
            "mergeSha": None,
            "fetchedAt": 100.0,
        }
    ]


def test_a_merged_prs_record_keeps_what_the_task_consumers_read_beside_the_served_fields(store: PullStore) -> None:
    github = Github()
    github.add(5, state="MERGED", merged_at=NEW, files=("a.py", "b.py"), behind=3)

    _read(store, github, 100.0)

    (record,) = store.find(number=5, detailed=True)
    assert record["detail"] == {
        "mergedAt": NEW,
        "mergeSha": f"{5:040x}"[::-1],
        "behindMain": 3,
        "files": ["a.py", "b.py"],
        "ci": {
            "createdAt": OLD,
            "mergeable": "MERGEABLE",
            "merged": True,
            "mergedAt": NEW,
            "commits": {"nodes": [{"commit": {"oid": f"{5:040x}", "checkSuites": {"nodes": [SUITE]}}}]},
            "timelineItems": {"nodes": []},
        },
    }
    assert "detail" not in store.find(number=5)[0]


def test_a_query_too_large_for_an_argument_reaches_gh_on_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def gh(command: list[str], **kwargs: str) -> subprocess.CompletedProcess[str]:
        seen.update(command=command, input=kwargs["input"])
        return subprocess.CompletedProcess(command, 0, '{"data": {"repository": {"p1": null}}}', "")

    monkeypatch.setattr(subprocess, "run", gh)
    query = "q" * 300_000

    assert query_github(REPO, query) == {"p1": None}
    assert sum(len(arg) for arg in seen["command"]) < 200
    assert json.loads(seen["input"]) == {"query": query, "variables": {"owner": "acme", "name": "widgets"}}


def test_each_query_logs_the_rate_limit_cost_github_returned(
    store: PullStore, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    github = Github()
    github.add(1)
    costs = iter([2])

    def gh(command: list[str], **kwargs: str) -> subprocess.CompletedProcess[str]:
        query = json.loads(kwargs["input"])["query"]
        data = {"rateLimit": {"cost": next(costs), "remaining": 4210, "resetAt": "2026-10-07T21:00:00Z"}}
        return subprocess.CompletedProcess(
            command, 0, json.dumps({"data": data | {"repository": github(REPO, query)}}), ""
        )

    monkeypatch.setattr(subprocess, "run", gh)

    with caplog.at_level(logging.INFO, logger="starpulse.pulls.pull_requests"):
        refresh_pull(REPO, 1, store, 100.0)

    logged = [record.getMessage() for record in caplog.records if "cost" in record.getMessage()]
    assert [(REPO in message, "cost 2" in message) for message in logged] == [(True, True)]


def test_a_pr_with_no_commits_is_recorded_with_an_empty_rollup_and_leaves_the_others_saved(store: PullStore) -> None:
    github = Github()
    github.add(1, checks={"lint": "SUCCESS"})
    github.add(2)
    node = github._node
    github._node = lambda number: node(number) | ({"commits": {"nodes": []}} if number == 2 else {})  # type: ignore[method-assign]

    _read(store, github, 100.0)

    assert {pull["number"]: (pull["checks"], pull["requiredChecks"]) for pull in store.find()} == {
        1: ("pass", [{"name": "lint", "result": "pass"}]),
        2: ("none", []),
    }


def test_a_refresh_request_reads_that_pr_alone_and_publishes_its_merge_without_the_next_refresh(
    store: PullStore,
) -> None:
    github = Github()
    github.add(1)
    github.add(2)
    _read(store, github, 100.0)
    github.add(1, state="MERGED", updated=NEW, merged_at=NEW)
    github.queries.clear()
    projected: list[str] = []
    sync = PullSync(store, BoardFeed(), (), github, lambda: 160.0, lambda: projected.append("project"))

    assert sync.request(REPO, 1) is True
    sync.serve_requests()

    (query,) = github.queries
    assert "p1: pullRequest(number: 1)" in query
    assert "pullRequest(number: 2)" not in query
    assert "open: pullRequests" not in query
    assert {pull["number"]: pull["state"] for pull in store.find()} == {1: "MERGED", 2: "OPEN"}
    assert projected == ["project"]


def test_a_merged_pr_is_recorded_with_its_merge_commit_and_time_and_an_open_one_with_neither(store: PullStore) -> None:
    github = Github()
    github.add(1)
    github.add(2, state="MERGED", merged_at="2026-10-07T12:30:00Z")

    _read(store, github, 100.0)

    open_pull, merged = store.find()
    assert (open_pull["mergedAt"], open_pull["mergeSha"]) == (None, None)
    assert (merged["mergedAt"], merged["mergeSha"]) == ("2026-10-07T12:30:00Z", f"{2:040x}"[::-1])


def test_a_sync_tracks_the_repositories_the_tasks_the_store_and_the_config_name(store: PullStore) -> None:
    store.save([{**_stored("acme/old", 1), "state": "MERGED"}])
    feed = BoardFeed()
    feed.put(task("PROJ-7", "In Progress", references=["https://github.com/acme/widgets/pull/9"]))

    sync = PullSync(store, feed, (Repo("skills", "skills", "pin-bump"),))

    assert sync.tracked() == ["acme/old", "acme/skills", "acme/widgets"]


def test_a_request_for_a_repository_nothing_tracks_is_refused_and_queues_no_read(store: PullStore) -> None:
    asked: list[str] = []
    sync = PullSync(store, BoardFeed(), (), lambda repo, query: asked.append(repo) or {})

    assert sync.request("acme/unknown", 1) is False
    sync.serve_requests()

    assert asked == []


def test_a_request_is_read_alone_and_projected_and_a_projection_that_fails_ends_nothing(
    store: PullStore, caplog: pytest.LogCaptureFixture
) -> None:
    github = Github()
    github.add(1, checks={"lint": "SUCCESS"})
    github.add(2)
    store.save([_stored(REPO, 2)])
    calls: list[str] = []

    def project() -> None:
        calls.append("project")
        raise RuntimeError("bad record")

    sync = PullSync(store, BoardFeed(), (), github, lambda: 100.0, project)

    assert sync.request(REPO, 1) is True
    sync.serve_requests()

    assert calls == ["project"]
    assert "failed to project" in caplog.text
    assert [(pull["number"], pull["checks"]) for pull in store.find()] == [(1, "pass"), (2, "none")]


def test_a_request_that_cannot_be_read_is_logged_and_the_next_one_is_still_served(
    store: PullStore, caplog: pytest.LogCaptureFixture
) -> None:
    github = Github()
    github.add(2)

    def graphql(repo: str, query: str) -> dict:
        if "p1: pullRequest" in query:
            raise IndexError("list index out of range")
        return github(repo, query)

    sync = PullSync(store, BoardFeed(), (), graphql, lambda: 100.0)
    store.save([_stored(REPO, 1)])

    sync.request(REPO, 1)
    sync.request(REPO, 2)
    sync.serve_requests()

    assert "acme/widgets#1 failed to refresh" in caplog.text
    assert [pull["number"] for pull in store.find()] == [1, 2]


def test_reconciling_the_open_records_closes_each_one_github_reports_closed_and_lists_nothing(
    store: PullStore,
) -> None:
    github = Github()
    github.add(1)
    github.add(2)
    github.add(3, state="MERGED", updated=NEW, merged_at=NEW)
    github.add(4, state="CLOSED", updated=NEW)
    store.save([_stored(REPO, number) for number in (1, 2, 3, 4)])
    github.queries.clear()
    sync = PullSync(store, BoardFeed(), (), github, lambda: 160.0)

    assert sync.reconcile_open() == 4
    sync.serve_requests()

    assert {pull["number"]: pull["state"] for pull in store.find()} == {1: "OPEN", 2: "OPEN", 3: "MERGED", 4: "CLOSED"}
    assert len(github.queries) == 4
    assert all("pullRequests" not in query for query in github.queries)  # a read of one pull request, never a listing


def test_reconcile_reads_a_merged_record_that_has_no_merge_sha(store: PullStore) -> None:
    github = Github()
    github.add(1, state="MERGED", updated=NEW, merged_at=NEW)
    github.add(2, state="MERGED", updated=NEW, merged_at=NEW)
    store.save([{**_stored(REPO, 1), "state": "MERGED", "mergedAt": NEW}])
    store.save([{**_stored(REPO, 2), "state": "MERGED", "mergedAt": NEW, "mergeSha": "a" * 40}])
    sync = PullSync(store, BoardFeed(), (), github, lambda: 160.0)

    assert sync.reconcile_open() == 1  # #2 already holds its merge commit
    sync.serve_requests()

    assert store.find(number=1)[0]["mergeSha"]
    assert sync.reconcile_open() == 0


def test_a_second_reconcile_reads_only_the_records_still_open(store: PullStore) -> None:
    github = Github()
    github.add(1)
    github.add(2, state="MERGED", updated=NEW, merged_at=NEW)
    store.save([_stored(REPO, 1), _stored(REPO, 2)])
    sync = PullSync(store, BoardFeed(), (), github, lambda: 160.0)
    sync.reconcile_open()
    sync.serve_requests()
    github.queries.clear()

    assert sync.reconcile_open() == 1
    sync.serve_requests()

    (query,) = github.queries
    assert "p1: pullRequest(number: 1)" in query
