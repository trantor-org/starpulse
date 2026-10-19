"""`task show` prints each task id and pull request number in a description as a link."""

from __future__ import annotations

from starpulse._internal.cli.agent_tasks import linkify

BASE = "http://board:8766/"
PULLS = [{"url": "https://github.com/acme/app/pull/123"}]
CARD = "[TASK-7](http://board:8766/?view=kanban&task=TASK-7)"


def test_a_bare_task_id_becomes_a_kanban_link() -> None:
    assert linkify("Fork from TASK-7.", BASE) == f"Fork from {CARD}."


def test_a_pull_number_links_to_the_tasks_pull_request() -> None:
    assert linkify("Fixed in #123", BASE, PULLS) == "Fixed in [#123](https://github.com/acme/app/pull/123)"


def test_a_pull_number_the_task_has_no_pull_for_stays_bare() -> None:
    assert linkify("See #456", BASE, PULLS) == "See #456"


def test_code_links_and_urls_are_left_unchanged() -> None:
    text = "`TASK-7` and ```\nTASK-7\n``` and [TASK-7](http://x/y) and https://h/TASK-7 and [ ] #123 and `#123`"

    assert linkify(text, BASE, PULLS) == text
