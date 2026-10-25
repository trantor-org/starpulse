"""A Task renders as markdown, and an edited rendering imports as Events by the operator marked break-glass (D5)."""

import json

import pytest

from starpulse.board.model.markdown import MarkdownRefusedError, imported, render
from starpulse._internal.server.writes import edit_task
from starpulse.tests.unit.board.test_task_history import served  # noqa: F401  (the fixture)


def test_an_untouched_rendering_imports_as_no_change(served) -> None:  # noqa: F811
    record = served[0].read("task-5")

    assert imported(render(record), record) == {}


def test_a_rendering_names_the_title_and_every_criterion(served) -> None:  # noqa: F811
    text = render(served[0].read("task-5"))

    assert text.startswith("# Draw the board\n")
    assert "- [ ] #1 It draws" in text
    assert "## Definition of Done" in text


def test_an_editor_round_trip_is_break_glass_field_and_criterion_events(served) -> None:  # noqa: F811
    built, feed, store, _ = served
    record = built.read("task-5")
    text = render(record).replace("# Draw the board", "# Draw it well").replace("- [ ] #1", "- [x] #1")
    body = {
        "task": "task-5",
        "base": record,
        "changes": imported(text, record),
        "breakGlass": True,
        "actor": "operator",
    }

    status, _ = edit_task("127.0.0.1", json.dumps(body).encode(), feed, built.read, built.edit)

    assert status == 200
    events = store.read("task", "task-5")[1:]
    assert [event.type for event in events] == ["FieldsEdited", "CriterionChecked"]
    assert {(event.writer, event.actor) for event in events} == {("break-glass", "operator")}
    assert events[0].payload["changes"] == {"title": "Draw it well"}


def test_an_ordinary_edit_is_not_marked_break_glass(served) -> None:  # noqa: F811
    built, feed, store, _ = served
    body = {"task": "task-5", "base": built.read("task-5"), "changes": {"title": "Plain"}}

    assert edit_task("127.0.0.1", json.dumps(body).encode(), feed, built.read, built.edit)[0] == 200

    assert store.read("task", "task-5")[-1].writer == "native-board"


@pytest.mark.parametrize("heading", ["Description", "Acceptance Criteria", "Implementation Plan"])
def test_an_edit_that_removes_a_section_is_refused_naming_it(served, heading) -> None:  # noqa: F811
    record = served[0].read("task-5")
    kept = [block for block in render(record).split("\n## ") if not block.startswith(heading)]

    with pytest.raises(MarkdownRefusedError, match=heading):
        imported("\n## ".join(kept), record)


def test_an_edit_that_adds_an_unknown_section_is_refused_naming_it(served) -> None:  # noqa: F811
    record = served[0].read("task-5")

    with pytest.raises(MarkdownRefusedError, match="Appendix"):
        imported(render(record) + "\n## Appendix\n\nnotes\n", record)


def test_an_edit_that_changes_the_status_is_refused(served) -> None:  # noqa: F811
    record = served[0].read("task-5")

    with pytest.raises(MarkdownRefusedError, match="Status"):
        imported(render(record).replace("- Status: To Do", "- Status: Done"), record)


def test_an_untouched_rendering_of_an_int_priority_imports_as_no_change(served) -> None:  # noqa: F811
    record = {**served[0].read("task-5"), "priority": 2}

    assert imported(render(record), record) == {}
