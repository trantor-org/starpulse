"""The PR store: every open and recently updated pull request of a repository, read in one query and served."""

import json
import logging
import re
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.config.config import Repo
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.pulls.pull_requests import GhUnavailableError, query_github
from starpulse._internal.pulls.pull_store import PullSync, refresh_repository
from starpulse._internal.pulls.pulls import AGE_HELP, PullStore

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
        #: PRs that exist but sit beyond the listings' reach, as an old merged PR does.
        self.unlisted: set[int] = set()

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
    ) -> None:
        """A PR; `checks` maps each required check to its conclusion, or to IN_PROGRESS while it runs."""
        self.pulls[number] = {
            "state": state,
            "updated": updated,
            "body": body,
            "checks": checks or {},
            "threads": threads,
            "merged_at": merged_at,
            "files": files,
            "behind": behind,
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
            "reviewThreads": {"nodes": [{"isResolved": resolved} for resolved in pull["threads"]]},
        }

    def __call__(self, repo: str, query: str) -> dict:
        assert repo == REPO
        self.queries.append(query)
        answer: dict = {}
        if "open: pullRequests" in query:
            listed = [(n, p) for n, p in self.pulls.items() if n not in self.unlisted]
            answer["open"] = {
                "pageInfo": {"hasNextPage": False},
                "nodes": [
                    {"number": n, "state": p["state"], "updatedAt": p["updated"]}
                    for n, p in listed
                    if p["state"] == "OPEN"
                ],
            }
            answer["recent"] = {
                "nodes": [
                    {"number": n, "state": p["state"], "updatedAt": p["updated"]}
                    for n, p in sorted(listed, key=lambda item: item[1]["updated"], reverse=True)
                ]
            }
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


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


def test_a_refresh_sends_one_query_for_the_repository_and_none_for_a_final_record(store: PullStore) -> None:
    github = Github()
    github.add(1, checks={"lint": "SUCCESS"})
    github.add(2, state="MERGED")
    refresh_repository(REPO, store, 100.0, github)
    github.queries.clear()

    refresh_repository(REPO, store, 160.0, github)

    (query,) = github.queries
    assert "p1: pullRequest(number: 1)" in query
    assert "pullRequest(number: 2)" not in query
    assert "states: OPEN" in query
    assert "orderBy: {field: UPDATED_AT, direction: DESC}" in query


def test_a_pr_opened_since_the_last_refresh_costs_one_more_query_for_it_alone(store: PullStore) -> None:
    github = Github()
    github.add(1)
    refresh_repository(REPO, store, 100.0, github)
    github.add(7, updated=NEW, body="Session: abc")
    github.queries.clear()

    refresh_repository(REPO, store, 160.0, github)

    listing, follow_up = github.queries
    assert "p1: pullRequest" in listing
    assert "p7: pullRequest" not in listing
    assert "p7: pullRequest(number: 7)" in follow_up
    assert "p1: pullRequest" not in follow_up
    assert "open: pullRequests" not in follow_up
    assert [pull["body"] for pull in store.find(number=7)] == ["Session: abc"]


def test_a_cold_store_reads_the_listing_then_every_pr_it_named_in_one_more_query(store: PullStore) -> None:
    github = Github()
    github.add(1)
    github.add(2, state="MERGED")

    refresh_repository(REPO, store, 100.0, github)

    assert len(github.queries) == 2
    assert {pull["number"]: pull["state"] for pull in store.find()} == {1: "OPEN", 2: "MERGED"}


def test_a_pr_merged_since_the_last_refresh_is_recorded_final_and_asked_for_no_more(store: PullStore) -> None:
    github = Github()
    github.add(1)
    refresh_repository(REPO, store, 100.0, github)
    github.add(1, state="MERGED", updated=NEW)

    refresh_repository(REPO, store, 160.0, github)
    github.queries.clear()
    refresh_repository(REPO, store, 220.0, github)

    assert [pull["state"] for pull in store.find(number=1)] == ["MERGED"]
    (query,) = github.queries
    assert "pullRequest(number: 1)" not in query


def test_a_final_pr_the_store_never_saw_is_read_only_when_updated_since_the_cursor(store: PullStore) -> None:
    github = Github()
    github.add(1, updated=NEW)
    refresh_repository(REPO, store, 100.0, github)
    github.add(2, state="MERGED", updated=OLD)  # merged and last touched before the newest record the store holds
    github.add(3, state="CLOSED", updated="2026-10-07T14:00:00Z")

    refresh_repository(REPO, store, 160.0, github)

    assert [pull["number"] for pull in store.find()] == [1, 3]


def test_a_merged_row_saved_without_its_merge_sha_is_read_again_until_it_has_one(store: PullStore) -> None:
    github = Github()
    github.add(1, state="MERGED", merged_at=OLD)
    github.add(2, state="MERGED", merged_at=OLD)
    store.save(
        [
            {**_stored(REPO, 1), "state": "MERGED"},  # saved before the store read the merge commit
            {**_stored(REPO, 2), "state": "MERGED", "mergedAt": OLD, "mergeSha": "a" * 40},
        ]
    )

    refresh_repository(REPO, store, 100.0, github)

    assert {pull["number"]: (pull["mergedAt"], pull["mergeSha"]) for pull in store.find()} == {
        1: (OLD, f"{1:040x}"[::-1]),
        2: (OLD, "a" * 40),
    }
    (query,) = github.queries
    assert "pullRequest(number: 1)" in query
    assert "pullRequest(number: 2)" not in query
    github.queries.clear()

    refresh_repository(REPO, store, 160.0, github)

    (query,) = github.queries
    assert "pullRequest(number: 1)" not in query


def test_a_required_check_turning_red_with_updated_at_unchanged_reaches_the_store_on_the_next_refresh(
    store: PullStore,
) -> None:
    github = Github()
    github.add(1, checks={"lint": "IN_PROGRESS", "test": "SUCCESS"})
    refresh_repository(REPO, store, 100.0, github)
    (before,) = store.find(number=1)

    github.add(
        1, checks={"lint": "FAILURE", "test": "SUCCESS"}
    )  # updatedAt stays OLD: a check finishing does not bump it
    refresh_repository(REPO, store, 160.0, github)
    (after,) = store.find(number=1)

    assert (before["checks"], before["updatedAt"]) == ("pending", OLD)
    assert (after["checks"], after["updatedAt"], after["fetchedAt"]) == ("failing", OLD, 160.0)
    assert after["requiredChecks"] == [{"name": "lint", "result": "failing"}, {"name": "test", "result": "pass"}]


def test_a_record_carries_the_facts_pr_status_prints(store: PullStore) -> None:
    github = Github()
    github.add(4, checks={"lint": "SUCCESS"}, threads=(True, False, False))

    refresh_repository(REPO, store, 100.0, github)

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
            "updatedAt": OLD,
            "mergedAt": None,
            "mergeSha": None,
            "fetchedAt": 100.0,
        }
    ]


def test_a_merged_prs_record_keeps_what_the_task_consumers_read_beside_the_served_fields(store: PullStore) -> None:
    github = Github()
    github.add(5, state="MERGED", merged_at=NEW, files=("a.py", "b.py"), behind=3)

    refresh_repository(REPO, store, 100.0, github)

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


def test_a_table_an_earlier_version_created_gains_the_detail_column_and_keeps_its_rows(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}")
    with engine.begin() as db:
        db.exec_driver_sql(
            "CREATE TABLE starpulse_pull_requests (repo VARCHAR NOT NULL, number INTEGER NOT NULL, state VARCHAR NOT NULL,"
            " is_draft BOOLEAN NOT NULL, mergeable VARCHAR NOT NULL, base VARCHAR NOT NULL, head VARCHAR NOT NULL,"
            " body TEXT NOT NULL, checks VARCHAR NOT NULL, required JSON NOT NULL, threads INTEGER NOT NULL,"
            " updated_at VARCHAR NOT NULL, fetched_at FLOAT NOT NULL, PRIMARY KEY (repo, number))"
        )
        db.exec_driver_sql(
            "INSERT INTO starpulse_pull_requests VALUES ('acme/widgets', 1, 'MERGED', 0, 'UNKNOWN', 'main', 'abc', '',"
            " 'pass', '[]', 0, '2026-10-07T12:00:00Z', 1.0)"
        )

    store = PullStore(engine)
    store.save([{**_stored(REPO, 2), "detail": {"files": ["a.py"]}}])

    assert {pull["number"]: pull["detail"] for pull in store.find(detailed=True)} == {1: None, 2: {"files": ["a.py"]}}


def test_a_table_an_earlier_version_created_gains_the_merge_columns_and_keeps_its_rows(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}")
    with engine.begin() as db:
        db.exec_driver_sql(
            "CREATE TABLE starpulse_pull_requests (repo VARCHAR NOT NULL, number INTEGER NOT NULL, state VARCHAR NOT NULL,"
            " is_draft BOOLEAN NOT NULL, mergeable VARCHAR NOT NULL, base VARCHAR NOT NULL, head VARCHAR NOT NULL,"
            " body TEXT NOT NULL, checks VARCHAR NOT NULL, required JSON NOT NULL, threads INTEGER NOT NULL,"
            " updated_at VARCHAR NOT NULL, fetched_at FLOAT NOT NULL, detail JSON, PRIMARY KEY (repo, number))"
        )
        db.exec_driver_sql(
            "INSERT INTO starpulse_pull_requests VALUES ('acme/widgets', 1, 'OPEN', 0, 'UNKNOWN', 'main', 'abc', '',"
            " 'pass', '[]', 0, '2026-10-07T12:00:00Z', 1.0, NULL)"
        )

    store = PullStore(engine)
    store.save([{**_stored(REPO, 2), "state": "MERGED", "mergedAt": NEW, "mergeSha": "a" * 40}])

    assert {pull["number"]: (pull["mergedAt"], pull["mergeSha"]) for pull in store.find()} == {
        1: (None, None),
        2: (NEW, "a" * 40),
    }


def test_a_pr_an_open_task_cites_is_read_when_the_store_lacks_it_or_holds_it_without_detail(store: PullStore) -> None:
    github = Github()
    github.add(1)
    github.add(8, state="MERGED", merged_at=OLD, updated="2026-10-01T00:00:00Z")
    github.add(9, state="MERGED", merged_at=OLD, updated="2026-10-01T00:00:00Z")
    github.unlisted = {8, 9}
    store.save([{**_stored(REPO, 9), "state": "MERGED"}])  # saved by a version that kept no detail

    refresh_repository(REPO, store, 100.0, github, linked={8, 9, 77})  # 77 does not exist on GitHub

    assert {pull["number"]: pull["detail"] is not None for pull in store.find(detailed=True)} == {
        1: True,
        8: True,
        9: True,
    }


def test_merged_rows_without_a_merge_sha_are_read_a_few_per_refresh_until_none_is_left(store: PullStore) -> None:
    github = Github()
    for number in range(1, 151):
        github.add(number, state="MERGED", merged_at=OLD)
    store.save([{**_stored(REPO, number), "state": "MERGED"} for number in range(1, 151)])

    refreshes = 0
    while any(pull["mergeSha"] is None for pull in store.find()):
        github.queries.clear()
        refresh_repository(REPO, store, 100.0 + refreshes, github)
        refreshes += 1
        assert len(re.findall(r"p\d+: pullRequest", github.queries[0])) <= 25
        assert refreshes <= 10

    assert refreshes == 6


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
    costs = iter([2, 1])

    def gh(command: list[str], **kwargs: str) -> subprocess.CompletedProcess[str]:
        query = json.loads(kwargs["input"])["query"]
        data = {"rateLimit": {"cost": next(costs), "remaining": 4210, "resetAt": "2026-10-07T21:00:00Z"}}
        return subprocess.CompletedProcess(
            command, 0, json.dumps({"data": data | {"repository": github(REPO, query)}}), ""
        )

    monkeypatch.setattr(subprocess, "run", gh)

    with caplog.at_level(logging.INFO, logger="starpulse._internal.pulls.pull_requests"):
        refresh_repository(REPO, store, 100.0)

    logged = [record.getMessage() for record in caplog.records if "cost" in record.getMessage()]
    assert [(REPO in message, f"cost {cost}" in message) for message, cost in zip(logged, (2, 1), strict=True)] == [
        (True, True),
        (True, True),
    ]


def test_a_sync_reads_the_repositories_the_tasks_the_store_and_the_config_name_and_survives_one_that_fails(
    store: PullStore,
) -> None:
    store.save([{**_stored("acme/old", 1), "state": "MERGED"}])
    feed = BoardFeed()
    feed.put(task("PROJ-7", "In Progress", references=["https://github.com/acme/widgets/pull/9"]))
    asked: list[str] = []

    def graphql(repo: str, query: str) -> dict:
        asked.append(repo)
        if repo == "acme/widgets":
            raise GhUnavailableError("widgets is not readable")
        return {"open": {"pageInfo": {"hasNextPage": False}, "nodes": []}, "recent": {"nodes": []}}

    PullSync(store, feed, (Repo("skills", "skills", "pin-bump"),), graphql, lambda: 100.0).refresh()

    assert sorted(asked) == ["acme/old", "acme/skills", "acme/widgets"]


def test_a_sync_reads_the_prs_open_tasks_cite_that_the_listings_do_not_reach() -> None:
    feed = BoardFeed()
    feed.put(task("PROJ-7", "In Progress", references=["https://github.com/acme/widgets/pull/9", "x"]))
    asked: list[str] = []

    def graphql(repo: str, query: str) -> dict:
        asked.append(query)
        return {"open": {"pageInfo": {"hasNextPage": False}, "nodes": []}, "recent": {"nodes": []}} | {"p9": None}

    PullSync(PullStore(create_engine("sqlite://")), feed, (), graphql, lambda: 100.0).refresh()

    assert "p9: pullRequest(number: 9)" in asked[-1]


def test_a_sync_projects_the_boards_pull_requests_after_each_read_and_survives_a_projection_that_fails(
    store: PullStore, caplog: pytest.LogCaptureFixture
) -> None:
    store.save([{**_stored("acme/old", 1), "state": "MERGED"}])
    calls: list[str] = []

    def graphql(repo: str, query: str) -> dict:
        calls.append("read")
        return {"open": {"pageInfo": {"hasNextPage": False}, "nodes": []}, "recent": {"nodes": []}}

    def project() -> None:
        calls.append("project")
        raise RuntimeError("bad record")

    PullSync(store, BoardFeed(), (), graphql, lambda: 100.0, project).refresh()

    assert calls == ["read", "project"]
    assert "failed to project" in caplog.text


def test_run_forever_projects_the_saved_store_before_the_first_read(
    store: PullStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def graphql(repo: str, query: str) -> dict:
        calls.append("read")
        return {"open": {"pageInfo": {"hasNextPage": False}, "nodes": []}, "recent": {"nodes": []}}

    def sleep(seconds: float) -> None:
        raise KeyboardInterrupt

    store.save([{**_stored("acme/old", 1), "state": "MERGED"}])
    monkeypatch.setattr(PullSync, "_idle", lambda _self, seconds: sleep(seconds))

    with pytest.raises(KeyboardInterrupt):
        PullSync(store, BoardFeed(), (), graphql, lambda: 100.0, lambda: calls.append("project")).run_forever(1.0)

    assert calls == ["project", "read", "project"]


def test_a_pr_with_no_commits_is_recorded_with_an_empty_rollup_and_leaves_the_others_saved(store: PullStore) -> None:
    github = Github()
    github.add(1, checks={"lint": "SUCCESS"})
    github.add(2)
    node = github._node
    github._node = lambda number: node(number) | ({"commits": {"nodes": []}} if number == 2 else {})  # type: ignore[method-assign]

    refresh_repository(REPO, store, 100.0, github)

    assert {pull["number"]: (pull["checks"], pull["requiredChecks"]) for pull in store.find()} == {
        1: ("pass", [{"name": "lint", "result": "pass"}]),
        2: ("none", []),
    }


def test_an_error_reading_one_repository_does_not_stop_the_others_or_end_run_forever(
    store: PullStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.save([{**_stored("acme/a", 1), "state": "MERGED"}, {**_stored("acme/b", 2), "state": "MERGED"}])
    asked: list[str] = []

    def graphql(repo: str, query: str) -> dict:
        asked.append(repo)
        if repo == "acme/a":
            raise IndexError("list index out of range")
        return {"open": {"pageInfo": {"hasNextPage": False}, "nodes": []}, "recent": {"nodes": []}}

    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt  # ends the loop the test is watching

    monkeypatch.setattr(PullSync, "_idle", lambda _self, seconds: sleep(seconds))

    with pytest.raises(KeyboardInterrupt):
        PullSync(store, BoardFeed(), (), graphql, lambda: 100.0).run_forever(1.0)

    assert asked == ["acme/a", "acme/b", "acme/a", "acme/b"]


def test_a_refresh_request_reads_that_pr_alone_and_publishes_its_merge_without_the_next_refresh(
    store: PullStore,
) -> None:
    github = Github()
    github.add(1)
    github.add(2)
    refresh_repository(REPO, store, 100.0, github)
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


def _record(repo: str, number: int, state: str, fetched: float) -> dict:
    return {
        "repo": repo,
        "number": number,
        "state": state,
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
        "fetchedAt": fetched,
    }


def test_age_gauge_reports_each_repository_newest_fetched_at_age_in_seconds(tmp_path: Path) -> None:
    store = PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))
    store.save(
        [
            _record("acme/widgets", 1, "OPEN", 900.0),
            _record("acme/widgets", 2, "OPEN", 940.0),
            _record("acme/skills", 7, "OPEN", 400.0),
        ]
    )

    assert store.age_gauge(1000.0).splitlines() == [
        f"# HELP starpulse_pull_store_age_seconds {AGE_HELP}",
        "# TYPE starpulse_pull_store_age_seconds gauge",
        'starpulse_pull_store_age_seconds{repo="acme/skills"} 600',
        'starpulse_pull_store_age_seconds{repo="acme/widgets"} 60',
    ]


def test_age_gauge_leaves_out_a_repository_holding_no_open_pull_request(tmp_path: Path) -> None:
    """A refresh rewrites only the open and the changed PRs, so a repository with none open ages without being stale."""
    store = PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))
    store.save([_record("acme/widgets", 1, "MERGED", 100.0), _record("acme/skills", 1, "OPEN", 990.0)])

    assert 'repo="acme/widgets"' not in store.age_gauge(1000.0)
    assert 'starpulse_pull_store_age_seconds{repo="acme/skills"} 10' in store.age_gauge(1000.0)


def test_a_merged_pr_is_recorded_with_its_merge_commit_and_time_and_an_open_one_with_neither(store: PullStore) -> None:
    github = Github()
    github.add(1)
    github.add(2, state="MERGED", merged_at="2026-10-07T12:30:00Z")

    refresh_repository(REPO, store, 100.0, github)

    open_pull, merged = store.find()
    assert (open_pull["mergedAt"], open_pull["mergeSha"]) == (None, None)
    assert (merged["mergedAt"], merged["mergeSha"]) == ("2026-10-07T12:30:00Z", f"{2:040x}"[::-1])
