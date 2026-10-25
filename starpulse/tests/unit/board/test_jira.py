"""The Jira board's start: its first poll is the feed's replay."""

import json
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from starpulse.board.adapters import jira
from starpulse.board.adapters.jira import JiraProject, board
from starpulse.board.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "jira"
WORKFLOW = "Payments Software Workflow"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_the_first_poll_is_the_feeds_replay_and_the_feed_is_ready_once_it_has_placed_every_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A start places every issue of the project; while it runs the feed builds no Ledger per issue.
    responses = {
        "": fixture("search_page_1"),
        "EgQIlMIC": fixture("search_page_2"),
        WORKFLOW: fixture("workflows_search"),
    }

    def fetch(path: str, query: Mapping[str, str]) -> Mapping[str, Any]:
        return responses[query.get("workflowName") or query.get("nextPageToken", "")]

    project = JiraProject(fetch, "PAY", WORKFLOW)
    monkeypatch.setattr(jira, "open_project", lambda settings: (project, "https://jira.example"))
    feed = BoardFeed()
    built: list[None] = []
    refresh = feed._refresh_ledgers
    monkeypatch.setattr(feed, "_refresh_ledgers", lambda: (built.append(None), refresh()))

    running = set(threading.enumerate())
    board({"interval": "0.01"}, Path(".")).start(feed, "test", EventLog("sqlite://"))

    assert feed.ready.wait(timeout=5)
    assert len(built) == 1
    assert sorted(task["id"] for task in feed.open_tasks()) == ["PAY-1", "PAY-2", "PAY-4"]
    monkeypatch.setattr(project, "scan", lambda put, retract: (_ for _ in ()).throw(SystemExit))
    for thread in set(threading.enumerate()) - running:
        if thread.name == "jira":
            thread.join(timeout=5)
            assert not thread.is_alive(), "the polling thread outlived its test"
