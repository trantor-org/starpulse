from pathlib import Path

import pytest
from sqlalchemy import create_engine
from starpulse.pulls.adapters.outbound.pull_requests import delivers
from starpulse.pulls.adapters.outbound.pulls import PullStore

URL = "https://github.com/acme/starpulse/pull/10"


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


def _save(store: PullStore, *, title: str, branch: str) -> None:
    store.save(
        [{
            "repo": "acme/starpulse",
            "number": 10,
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "UNKNOWN",
            "baseRefName": "main",
            "headRefOid": "a" * 40,
            "headRefName": branch,
            "title": title,
            "body": "",
            "checks": "pass",
            "requiredChecks": [],
            "threads": 0,
            "updatedAt": "2026-10-06T21:14:09Z",
            "mergedAt": None,
            "mergeSha": None,
            "fetchedAt": 0.0,
            "detail": None,
        }]
    )


def test_a_pull_request_titled_for_another_task_is_not_this_tasks_delivery(store: PullStore) -> None:
    _save(store, title="task-9: fix", branch="fix-x")
    assert delivers(store, URL, "task-1") is False
    assert delivers(store, URL, "task-9") is True
