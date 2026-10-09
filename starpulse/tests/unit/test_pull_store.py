"""The PR store: every open and recently updated pull request of a repository, read in one query and served."""

import json
import logging
import re
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.pulls.pull_requests import GhUnavailableError
from starpulse._internal.pulls.pull_store import PullSync, refresh_repository
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.config.config import Repo
from starpulse._internal.pulls.pulls import PullStore

REPO = "acme/widgets"
OLD, NEW = "2026-10-07T12:00:00Z", "2026-10-07T13:00:00Z"
_PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}


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
    ) -> None:
        """A PR; `checks` maps each required check to its conclusion, or to IN_PROGRESS while it runs."""
        self.pulls[number] = {
            "state": state,
            "updated": updated,
            "body": body,
            "checks": checks or {},
            "threads": threads,
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
            "commits": {"nodes": [{"commit": {"statusCheckRollup": {"contexts": {"nodes": contexts}}}}]},
            "reviewThreads": {"nodes": [{"isResolved": resolved} for resolved in pull["threads"]]},
        }

    def __call__(self, repo: str, query: str) -> dict:
        assert repo == REPO
        self.queries.append(query)
        answer: dict = {}
        if "open: pullRequests" in query:
            listed = [(n, p) for n, p in self.pulls.items()]
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
            "fetchedAt": 100.0,
        }
    ]


def test_each_query_logs_the_rate_limit_cost_github_returned(
    store: PullStore, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    github = Github()
    github.add(1)
    costs = iter([2, 1])

    def gh(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        query = next(arg for arg in command if arg.startswith("query="))
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
