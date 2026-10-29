"""`POST /api/answer`: the operator answers a Needs attention question on the card, and no agent relays it."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.store import EventStore
from starpulse.views.writes import answer_task, operator_refusal

from tests.unit.board.test_native_lifecycle import LAN, _in_progress, _park, _scan, _text

QUESTION = "pick a host"
ANSWER_LINE = re.compile(r"^Operator answer \(board:operator#(?P<id>[\w-]+)\): (?P<answer>.*)$", re.M)


def _answer(feed: Any, built: Board, **body: object) -> tuple[int, dict[str, Any]]:
    return answer_task(LAN, json.dumps(body).encode(), feed, built.read, built.edit)


def _asking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Board]:
    """A native board whose `task-1` waits in Needs attention on `QUESTION`."""
    feed, built = _in_progress(tmp_path, monkeypatch)
    assert _park(feed, built, task="task-1", operator=QUESTION)[0] == 200
    _scan(tmp_path, feed)
    return feed, built


def test_an_answer_records_an_operator_answer_line_under_the_question_and_leaves_the_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _asking(tmp_path, monkeypatch)

    status, body = _answer(feed, built, task="task-1", answer="use unraid")

    assert status == 200 and body["task"] == "task-1"
    found = ANSWER_LINE.search((built.read("task-1") or {})["description"])
    assert found is not None and found["answer"] == "use unraid" and found["id"] == body["id"]
    assert "status: Needs attention\n" in _text(tmp_path, "task-1")
    assert (built.read("task-1") or {})["description"].count("## Needs attention") == 1
    assert QUESTION in (built.read("task-1") or {})["description"]


def test_an_answer_to_a_task_outside_needs_attention_is_refused_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch)
    before = _text(tmp_path, "task-1")

    status, body = _answer(feed, built, task="task-1", answer="use unraid")

    assert status == 409 and "Needs attention" in body["error"]
    assert _text(tmp_path, "task-1") == before


def test_a_blank_answer_is_a_400_and_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feed, built = _asking(tmp_path, monkeypatch)
    before = _text(tmp_path, "task-1")

    status, _ = _answer(feed, built, task="task-1", answer="  ")

    assert status == 400
    assert _text(tmp_path, "task-1") == before


def test_an_answer_writes_a_trajectory_event_naming_the_operator_the_question_and_the_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _asking(tmp_path, monkeypatch)

    assert _answer(feed, built, task="task-1", answer="use unraid")[0] == 200

    store = EventStore(EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").engine)
    last = store.read("task", "task-1")[-1]
    assert (last.type, last.actor) == ("CommentAdded", "operator")
    assert QUESTION in last.payload["text"] and "use unraid" in last.payload["text"]


@pytest.mark.parametrize(
    ("origin", "host", "fetch_site", "authorization", "refused"),
    [
        ("https://h:8766", "h:8766", "same-origin", None, False),
        (None, "h:8766", "same-origin", None, True),
        ("https://h:8766", "h:8766", None, None, True),
        ("https://h:8766", "h:8766", "cross-site", None, True),
        ("https://h:8766", "h:8766", "same-origin", "Bearer agent-token", True),
        ("https://evil.example", "h:8766", "same-origin", None, True),
    ],
)
def test_only_a_same_origin_browser_request_with_no_token_is_the_operator(
    origin: str | None, host: str, fetch_site: str | None, authorization: str | None, refused: bool
) -> None:
    refusal = operator_refusal(origin, host, fetch_site, authorization)

    assert (refusal is not None and refusal[0] == 403) is refused
