"""`POST /api/resume`: recreate a parked task's session with the operator's reply as its first message."""

from __future__ import annotations

from typing import Any

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Written
from starpulse.contracts.adapters import StartFailedError
from starpulse.contracts.api.dto.requests import ResumeRequest
from starpulse.runtime.adapter_kit import task
from starpulse.views.application.commands.moves import resume_requested

from tests.machines import ROLES

URL = "https://claude.ai/code/session_01"


class Seams:
    """A session-start service and a task editor that record what they are asked."""

    def __init__(self, failure: str | None = None) -> None:
        self.failure = failure
        self.started: list[tuple[str, dict[str, Any]]] = []
        self.comments: list[tuple[str, dict[str, Any], str]] = []

    def start_session(self, name: str, **kwargs: Any) -> str:
        if self.failure:
            raise StartFailedError(self.failure)
        self.started.append((name, kwargs))
        return URL

    def edit(self, name: str, changes: dict[str, Any], comment: str, **_: Any) -> Written:
        self.comments.append((name, changes, comment))
        return Written(True, "ok")

    def resume(self, feed: BoardFeed, **fields: Any) -> tuple[int, dict[str, Any]]:
        request = ResumeRequest(task="PROJ-3", **fields)
        return resume_requested(request, feed, self.start_session, self.edit)


def parked(state: str) -> BoardFeed:
    feed = BoardFeed(roles=ROLES)
    feed.put(task("PROJ-3", state, profile="@agent-deep-high"))
    return feed


@pytest.mark.parametrize("state", ["Review", "Needs Attention", "Waiting"])
def test_a_resume_starts_the_session_with_the_reply_and_records_its_link_on_the_task(state):
    seams = Seams()

    status, body = seams.resume(parked(state), text="fix the typo")

    assert (status, body["task"], body["url"]) == (200, "PROJ-3", URL)
    assert seams.started == [("PROJ-3", {"verb": "Resume", "text": "fix the typo"})]
    assert seams.comments == [("PROJ-3", {}, f"Resumed in {URL}")]


def test_a_resume_with_no_reply_sends_none():
    seams = Seams()

    status, _ = seams.resume(parked("Review"))

    assert status == 200
    assert seams.started == [("PROJ-3", {"verb": "Resume", "text": None})]


@pytest.mark.parametrize("state", ["Ready", "In Progress", "Done"])
def test_a_resume_is_refused_outside_the_lanes_a_session_parks_from(state):
    seams = Seams()

    status, body = seams.resume(parked(state), text="hi")

    assert status == 409
    assert "review" in body["error"]
    assert seams.started == seams.comments == []


def test_a_resume_the_service_refuses_is_a_502_that_records_nothing():
    seams = Seams(failure="TASK-3 has a live session")

    status, body = seams.resume(parked("Review"))

    assert (status, body) == (502, {"error": "TASK-3 has a live session"})
    assert seams.comments == []


def test_a_resume_without_a_session_start_service_is_a_404():
    request = ResumeRequest(task="PROJ-3")

    status, _ = resume_requested(request, parked("Review"), None, Seams().edit)

    assert status == 404
