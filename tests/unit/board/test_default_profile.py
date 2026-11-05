"""A summary with no profile of its own draws the board's default for its `kind-*` and `size-*` labels."""

from __future__ import annotations

from starpulse.board.model.feed.shared import summary_agent

DEFAULTS = {"execute": {"2": "@agent-standard-medium"}, "spike": {"2": "@agent-deep-low"}}
ROW = {
    "id": "TASK-1",
    "title": "t",
    "state": "Proposed",
    "assignee": "",
    "released": None,
    "labels": ["kind-execute", "size-2"],
    "milestone": "",
    "type": "story",
    "updated_at": 0.0,
    "meta": {},
}


def test_a_summary_without_a_profile_takes_the_default_for_its_kind_and_size() -> None:
    agent = summary_agent(ROW, defaults=DEFAULTS)

    assert (agent["profile"], agent["model"]) == ("@agent-standard-medium", "@agent-standard-medium")


def test_a_profile_in_the_summary_wins_over_the_default() -> None:
    agent = summary_agent(ROW | {"meta": {"profile": "@agent-deep-high"}}, defaults=DEFAULTS)

    assert agent["profile"] == "@agent-deep-high"


def test_a_summary_whose_kind_and_size_the_defaults_lack_stays_empty() -> None:
    agent = summary_agent(ROW | {"labels": ["kind-execute", "size-8"]}, defaults=DEFAULTS)

    assert (agent["profile"], agent["model"]) == (None, "")
