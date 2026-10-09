"""The native task editor over copies of real Backlog.md task files: each field edits alone, and a Done task completes."""

import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from starpulse._internal.board import native
from starpulse._internal.board.seam import Board
from starpulse._internal.board.upstream_backlog import _split

FIXTURE = Path(__file__).resolve().parent.parent.parent / "fixtures" / "native_board"
STATUSES = ["Ready", "In Progress", "Waiting", "Needs attention", "Review", "Done"]
#: Real trantor task files: a Done task with every field, one in `completed/`, a Waiting one with Start Criteria and
#: a bare one with no references, documentation, modified files, plan or notes.
TASKS = ["TASK-2521", "TASK-2529", "TASK-3201", "TASK-1566"]
#: A record field the editor writes as a key of the task's front matter.
FRONT = {
    "title": "title",
    "type": "type",
    "status": "status",
    "priority": "priority",
    "profile": "assignee",
    "labels": "labels",
    "milestone": "milestone",
    "dependencies": "dependencies",
    "references": "references",
    "documentation": "documentation",
    "modifiedFiles": "modified_files",
}
#: A field the editor writes between a pair of section markers of the body.
SECTIONS = {
    "description": "SECTION:DESCRIPTION",
    "plan": "SECTION:PLAN",
    "notes": "SECTION:NOTES",
    "appendNotes": "SECTION:NOTES",
    "finalSummary": "SECTION:FINAL_SUMMARY",
    "acceptanceCriteria": "AC",
    "definitionOfDone": "DOD",
}
#: What each edit changes the field to, given the record the task has.
EDITS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "title": lambda record: f"{record['title']} reworded",
    "type": lambda record: "bug",
    "status": lambda record: "Review",
    "priority": lambda record: "low" if record["priority"] != "low" else "high",
    "profile": lambda record: "@agent-deep-medium",
    "labels": lambda record: [*record["labels"], "round-trip"],
    "milestone": lambda record: "m-999",
    "dependencies": lambda record: [*record["dependencies"], "TASK-1"],
    "references": lambda record: [*record["references"], "https://github.com/trantor-org/starpulse/pull/1"],
    "documentation": lambda record: [*record["documentation"], "docs/services/ai/starpulse.md"],
    "modifiedFiles": lambda record: [*record["modifiedFiles"], "starpulse/new.py"],
    "description": lambda record: f"{record['description']}\n\nAnd a second paragraph.",
    "plan": lambda record: "1. read\n2. write",
    "notes": lambda record: "Rewritten notes.\n\n**Holder:** 123",
    "appendNotes": lambda record: "Appended note.",
    "finalSummary": lambda record: "Shipped in PR 1.",
}


def _checklist(edit: str, field: str) -> Callable[[dict[str, Any]], Any]:
    def change(record: dict[str, Any]) -> Any:
        items = [dict(item) for item in record[field]]
        match edit:
            case "add":
                items.append({"text": "A new item", "checked": False})
            case "check":
                items = [{**item, "checked": True} for item in items]
            case "uncheck":
                items = [{**item, "checked": False} for item in items]
            case "remove":
                items = items[1:]
            case "reword":
                items[0]["text"] += " reworded"
        return items

    return change


for _field in ("acceptanceCriteria", "definitionOfDone"):
    for _edit in ("add", "check", "uncheck", "remove", "reword"):
        EDITS[f"{_field}:{_edit}"] = _checklist(_edit, _field)


@pytest.fixture
def served(tmp_path: Path) -> tuple[Board, Path]:
    """A native board on trantor's lanes whose `tasks/` and `completed/` hold copies of real task files."""
    root = tmp_path / ".starpulse" / "board"
    root.mkdir(parents=True)
    (root / "config.yml").write_text(
        yaml.safe_dump({"project_name": "trantor", "statuses": STATUSES, "task_prefix": "task"})
    )
    for folder in ("tasks", "completed"):
        shutil.copytree(FIXTURE / folder, root / folder)
    return native.board({}, tmp_path), root


def _file(root: Path, task: str) -> Path:
    return next(path for folder in ("tasks", "completed") for path in (root / folder).glob(f"{task.lower()}-*.md"))


def _blank(body: str, marker: str) -> str:
    """`body` with what sits between a section's markers taken out."""
    return re.sub(rf"(<!-- {marker}:BEGIN -->).*?(<!-- {marker}:END -->)", r"\1\2", body, flags=re.S)


def _record(built: Board, task: str) -> dict[str, Any]:
    assert built.read is not None
    record = dict(built.read(task) or {})
    record.pop("start_criteria")  # derived from the description, which an edit of the description changes
    return record


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("edit", EDITS)
def test_field_round_trip_edits_one_field_and_nothing_else(served: tuple[Board, Path], task: str, edit: str) -> None:
    built, root = served
    assert built.edit is not None
    field = edit.split(":")[0]
    path = _file(root, task)
    before_frontmatter, before_body = _split(path.read_text())
    before = _record(built, task)
    value = EDITS[edit](before)

    written = built.edit(task, {field: value}, "")

    assert written.ok, written.output
    frontmatter, body = _split(path.read_text())
    after = _record(built, task)
    if field == "appendNotes":
        assert after == {**before, "notes": f"{before['notes']}\n{value}".strip()}
    elif field in ("acceptanceCriteria", "definitionOfDone"):
        assert {key: item for key, item in after.items() if key != field} == {
            key: item for key, item in before.items() if key != field
        }
        assert [(item["text"], item["checked"]) for item in after[field]] == [
            (item["text"], item["checked"]) for item in value
        ]
        assert [kept["n"] for kept, sent in zip(after[field], value, strict=True) if "n" in sent] == [
            sent["n"] for sent in value if "n" in sent
        ]
    else:
        assert after == {**before, field: value}
    if field in FRONT:
        assert body == before_body
        assert {key: item for key, item in frontmatter.items() if key != FRONT[field]} == {
            key: item for key, item in before_frontmatter.items() if key != FRONT[field]
        }
    else:
        assert frontmatter == before_frontmatter
        marker = SECTIONS[field]
        if f"<!-- {marker}:BEGIN -->" in before_body:
            assert _blank(body, marker) == _blank(before_body, marker)
        else:
            assert body.startswith(before_body.rstrip("\n"))  # the section is new, after everything the file had
            assert f"<!-- {marker}:BEGIN -->" in body[len(before_body.rstrip("\n")) :]


@pytest.mark.parametrize("task", TASKS)
def test_field_round_trip_of_a_comment_adds_one_comment_and_nothing_else(served: tuple[Board, Path], task: str) -> None:
    built, root = served
    assert built.edit is not None
    path = _file(root, task)
    before_frontmatter, before_body = _split(path.read_text())
    before = _record(built, task)

    assert built.edit(task, {}, "Checked on the fixture.").ok

    frontmatter, body = _split(path.read_text())
    after = _record(built, task)
    assert frontmatter == before_frontmatter
    assert _blank(body, "COMMENTS") == _blank(before_body, "COMMENTS") or "<!-- COMMENTS:BEGIN -->" not in before_body
    assert [comment["text"] for comment in after["comments"]] == [
        *(comment["text"] for comment in before["comments"]),
        "Checked on the fixture.",
    ]
    assert after["comments"][: len(before["comments"])] == before["comments"]
    assert {key: item for key, item in after.items() if key != "comments"} == {
        key: item for key, item in before.items() if key != "comments"
    }


@pytest.mark.parametrize("task", TASKS)
def test_field_round_trip_of_an_edit_to_every_field_at_once_keeps_every_other_byte(
    served: tuple[Board, Path], task: str
) -> None:
    built, root = served
    assert built.edit is not None
    before = _record(built, task)
    changes = {
        field: EDITS.get(field, EDITS.get(f"{field}:add", lambda _: None))(before)
        for field in FRONT.keys() | SECTIONS.keys() - {"appendNotes"}
    }

    assert built.edit(task, changes, "").ok

    assert {key: item for key, item in _record(built, task).items() if key not in changes} == {
        key: item for key, item in before.items() if key not in changes
    }
    assert not built.edit(task, {"comments": []}, "").ok, "comments are appended, never set"


def test_field_round_trip_refuses_an_unknown_status_and_writes_nothing(served: tuple[Board, Path]) -> None:
    built, root = served
    assert built.edit is not None
    path = _file(root, "TASK-3201")
    before = path.read_text()

    written = built.edit("TASK-3201", {"title": "Mine", "status": "Shipped"}, "")

    assert not written.ok and "Shipped" in written.output
    assert path.read_text() == before


def test_field_round_trip_spells_a_status_as_the_lane_does(served: tuple[Board, Path]) -> None:
    built, root = served
    assert built.edit is not None

    assert built.edit("TASK-3201", {"status": "needs attention"}, "").ok

    assert _split(_file(root, "TASK-3201").read_text())[0]["status"] == "Needs attention"


def test_field_round_trip_refuses_a_non_text_list_item_and_writes_nothing(served: tuple[Board, Path]) -> None:
    built, root = served
    assert built.edit is not None
    path = _file(root, "TASK-3201")
    before = path.read_text()

    written = built.edit("TASK-3201", {"title": "Mine", "modifiedFiles": ["ok.py", 3]}, "")

    assert not written.ok
    assert path.read_text() == before


def test_native_complete_moves_a_done_task_to_completed_and_the_reader_still_resolves_it(
    served: tuple[Board, Path],
) -> None:
    built, root = served
    assert built.complete is not None and built.read is not None
    source = _file(root, "TASK-2521")
    before = built.read("TASK-2521")
    text = source.read_text()

    written = built.complete("TASK-2521")

    assert written.ok, written.output
    assert not source.exists()
    assert (root / "completed" / source.name).read_text() == text
    assert built.read("TASK-2521") == before


def test_native_complete_refuses_a_task_that_is_not_done_and_leaves_its_file(served: tuple[Board, Path]) -> None:
    built, root = served
    assert built.complete is not None
    source = _file(root, "TASK-3201")

    written = built.complete("TASK-3201")

    assert not written.ok and "Done" in written.output
    assert source.parent == root / "tasks"


def test_native_complete_refuses_a_task_already_completed_and_one_with_no_file(served: tuple[Board, Path]) -> None:
    built, root = served
    assert built.complete is not None

    assert not built.complete("TASK-2529").ok
    assert not built.complete("TASK-404").ok
    assert _file(root, "TASK-2529").parent == root / "completed"


def test_native_complete_leaves_a_completed_task_editable(served: tuple[Board, Path]) -> None:
    built, root = served
    assert built.complete is not None and built.edit is not None

    assert built.edit("TASK-2529", {"finalSummary": "Reworded."}, "").ok

    assert _split(_file(root, "TASK-2529").read_text())[1].count("Reworded.") == 1
    assert _file(root, "TASK-2529").parent == root / "completed"
