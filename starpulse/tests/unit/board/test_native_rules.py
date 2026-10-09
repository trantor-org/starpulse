"""The native board's `[board] rules`: record-level rules a write must satisfy, enforced where every task write lands."""

from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.board.native import board
from starpulse._internal.board.seam import Board
from starpulse._internal.config.config import load
from starpulse._internal.machines.transitions import DEFAULT_STATUSES
from starpulse.tests.unit.board.test_native import native_root, write_task

PULL = "https://github.com/acme/app/pull/5"
#: A move to Done needs a pull request among the task's references.
DONE_NEEDS_PR: dict[str, Any] = {
    "on": {"to": "Done"},
    "require": {"field": {"field": "references", "matches": r"/pull/\d+$", "min": 1}},
    "reason": "Done needs a pull request in references",
    "skill": "completing-tasks",
}


def ruled(base: Path, rules: list[dict[str, Any]], status: str = "In Progress", **fields: object) -> tuple[Path, Board]:
    """A native board with the default lanes and `rules`, holding `task-1` in `status`."""
    board({}, base)  # makes the default lanes
    return write_task(base, "task-1", status, **fields), board({"rules": rules}, base)


def test_a_rule_refuses_a_move_into_its_state_with_its_reason_and_skill_and_writes_nothing(tmp_path: Path) -> None:
    path, built = ruled(tmp_path, [DONE_NEEDS_PR])
    before = path.read_text()
    assert built.writer is not None

    written = built.writer("task-1", "Done", "operator")

    assert (written.ok, written.output, written.skill) == (False, DONE_NEEDS_PR["reason"], "completing-tasks")
    assert path.read_text() == before


def test_a_rule_lets_the_move_land_once_its_requirement_holds(tmp_path: Path) -> None:
    path, built = ruled(tmp_path, [DONE_NEEDS_PR], references=f"[{PULL}]")
    assert built.writer is not None

    assert built.writer("task-1", "Done", "operator").ok
    assert "status: Done\n" in path.read_text()


def test_a_rule_does_not_apply_to_a_move_into_another_state(tmp_path: Path) -> None:
    path, built = ruled(tmp_path, [DONE_NEEDS_PR], status="To Do")
    assert built.writer is not None

    assert built.writer("task-1", "In Progress", "agent").ok
    assert "status: In Progress\n" in path.read_text()


@pytest.mark.parametrize(
    ("rule", "complaint"),
    [
        ({"on": {"to": "Done"}, "require": {"field": {"field": "references", "min": 1}}}, "reason"),
        ({"on": {}, "require": {"field": {"field": "references", "min": 1}}, "reason": "r"}, "on"),
        ({"on": {"to": "Done"}, "require": {"colour": {"is": "red"}}, "reason": "r"}, "colour"),
        ({"on": {"to": "Done"}, "require": {"field": {"field": "references"}}, "reason": "r"}, "field"),
        (
            {"on": {"to": "Done"}, "require": {"field": {"field": "references", "matches": "("}}, "reason": "r"},
            "matches",
        ),
    ],
)
def test_a_rule_the_board_cannot_read_is_a_startup_error_naming_it(
    tmp_path: Path, rule: dict[str, Any], complaint: str
) -> None:
    board({}, tmp_path)

    with pytest.raises(ValueError, match=rf"rules\[0\].*{complaint}"):
        board({"rules": [rule]}, tmp_path)
    assert list(native_root(tmp_path).glob("tasks/*")) == []


def test_a_rule_exempts_the_actors_it_names_on_every_write_path(tmp_path: Path) -> None:
    exempt = {**DONE_NEEDS_PR, "unless_actor": ["dagu/reconciler"]}
    path, built = ruled(tmp_path, [exempt])
    assert built.writer is not None

    assert not built.writer("task-1", "Done", "agent").ok
    assert not built.writer("task-1", "Done", "operator").ok
    assert built.writer("task-1", "Done", "dagu/reconciler").ok
    assert "status: Done\n" in path.read_text()


def test_a_write_rule_judges_every_write_whatever_the_state_and_names_no_state_of_its_own(tmp_path: Path) -> None:
    capital = {
        "on": {"write": True},
        "require": {"field": {"field": "title", "matches": "^[A-Z]"}},
        "reason": "A title starts with a capital",
    }
    path, built = ruled(tmp_path, [capital])
    assert built.edit is not None and built.create is not None and built.archive is not None
    assert built.assign is not None
    before = path.read_text()

    assert built.edit("task-1", {"title": "lower"}, "") == (False, "A title starts with a capital", "", False, "")
    assert path.read_text() == before
    assert built.edit("task-1", {"title": "Upper"}, "").ok
    assert not built.create("lower", {}).ok
    assert [file.name for file in native_root(tmp_path).glob("tasks/*.md")] == [path.name]
    assert built.create("Upper", {}).ok
    assert built.assign("task-1", "@agent-deep-high").ok


def test_a_rule_judges_a_write_that_leaves_the_task_in_its_state_only_when_it_says_while(tmp_path: Path) -> None:
    needs_ref = {
        "on": {"to": "In Progress"},
        "require": {"field": {"field": "references", "min": 1}},
        "reason": "needs a reference",
    }
    path, built = ruled(tmp_path, [needs_ref])
    assert built.edit is not None
    assert built.edit("task-1", {"priority": "high"}, "").ok  # entered earlier; this write does not enter it

    staying = ruled(tmp_path / "second", [{**needs_ref, "on": {"to": "In Progress", "while": True}}])[1]
    assert staying.edit is not None
    assert not staying.edit("task-1", {"priority": "high"}, "").ok


def test_the_actor_a_write_names_reaches_the_rules_of_an_edit_an_archive_a_create_and_an_assign(tmp_path: Path) -> None:
    only_the_bot = {
        "on": {"write": True},
        "require": {"field": {"field": "priority", "in": ["high"]}},
        "reason": "Only the bot writes a task that is not high priority",
        "unless_actor": ["dagu/bot"],
    }
    path, built = ruled(tmp_path, [only_the_bot])
    assert built.edit is not None and built.create is not None and built.archive is not None
    assert built.assign is not None

    assert not built.edit("task-1", {"priority": "low"}, "").ok
    assert built.edit("task-1", {"priority": "low"}, "", actor="dagu/bot").ok
    assert not built.assign("task-1", "@agent-deep-high").ok
    assert built.assign("task-1", "@agent-deep-high", actor="dagu/bot").ok
    assert not built.create("lower", {}).ok
    assert built.create("lower", {}, actor="dagu/bot").ok
    assert not built.archive("task-1", "obsolete").ok
    assert path.exists()
    assert built.archive("task-1", "obsolete", actor="dagu/bot").ok


def done_needs(require: dict[str, Any]) -> dict[str, Any]:
    return {"on": {"to": "Done"}, "require": require, "reason": "refused"}


def lands(base: Path, require: dict[str, Any], body: str = "", **fields: object) -> bool:
    """Whether the move of `task-1` to Done lands under a rule requiring `require`; `body` is appended to its file."""
    path, built = ruled(base, [done_needs(require)], **fields)
    path.write_text(path.read_text() + body)
    assert built.writer is not None
    written = built.writer("task-1", "Done", "operator")
    assert written.ok or written.output == "refused"
    return written.ok


SIZES = {"label": {"prefix": "size-", "in": [1, 2, 3, 5, 8]}}
NEEDS_HUMAN = {"label": {"contains": "needs-human"}}


@pytest.mark.parametrize(
    ("require", "labels", "expected"),
    [
        (NEEDS_HUMAN, "[needs-human, size-3]", True),
        (NEEDS_HUMAN, "[size-3]", False),
        (SIZES, "[size-3, bug]", True),
        (SIZES, "[size-4]", False),
        (SIZES, "[size-3, size-4]", False),
        (SIZES, "[bug]", False),
    ],
)
def test_a_label_primitive_reads_the_labels_a_task_has(
    tmp_path: Path, require: dict[str, Any], labels: str, expected: bool
) -> None:
    assert lands(tmp_path, require, labels=labels) is expected


ATTENTION = "\n## Needs attention\n\n{}\n\n## Other\n\nsee task-9\n"


@pytest.mark.parametrize(
    ("require", "body", "expected"),
    [
        ({"section": {"heading": "Needs attention"}}, ATTENTION.format(""), True),
        ({"section": {"heading": "Needs attention"}}, "\n## Other\n\ntext\n", False),
        ({"section": {"heading": "Needs attention", "nonempty": True}}, ATTENTION.format("waiting on review"), True),
        ({"section": {"heading": "Needs attention", "nonempty": True}}, ATTENTION.format(""), False),
        ({"section": {"heading": "Needs attention", "nonempty": True}}, "", False),
        ({"section": {"heading": "Needs attention", "not_matching": r"\btask-\d+\b"}}, ATTENTION.format("none"), True),
        (
            {"section": {"heading": "Needs attention", "not_matching": r"\btask-\d+\b"}},
            ATTENTION.format("see task-2"),
            False,
        ),
        (
            {"section": {"heading": "Needs attention", "not_matching": r"\btask-\d+\b", "except_self": True}},
            ATTENTION.format("this is task-1"),
            True,
        ),
        (
            {"section": {"heading": "Needs attention", "not_matching": r"\btask-\d+\b", "except_self": True}},
            ATTENTION.format("this is task-1, not task-2"),
            False,
        ),
    ],
)
def test_a_section_primitive_reads_the_body_section_under_its_heading(
    tmp_path: Path, require: dict[str, Any], body: str, expected: bool
) -> None:
    assert lands(tmp_path, require, body) is expected


@pytest.mark.parametrize(
    ("combinator", "labels", "expected"),
    [
        ("any_of", "[a]", True),
        ("any_of", "[]", False),
        ("exactly_one", "[a]", True),
        ("exactly_one", "[a, b]", False),
        ("exactly_one", "[]", False),
        ("none_of", "[]", True),
        ("none_of", "[b]", False),
        ("all_of", "[a, b]", True),
        ("all_of", "[a]", False),
    ],
)
def test_a_combinator_holds_by_how_many_of_its_primitives_hold(
    tmp_path: Path, combinator: str, labels: str, expected: bool
) -> None:
    require = {combinator: [{"label": {"contains": "a"}}, {"label": {"contains": "b"}}]}

    assert lands(tmp_path, require, labels=labels) is expected


def test_a_dependencies_primitive_holds_when_every_dependency_is_in_a_named_state(tmp_path: Path) -> None:
    done = {"dependencies": {"all_in": ["Done"]}}
    path, built = ruled(tmp_path, [done_needs(done)], dependencies="[task-2]")
    write_task(tmp_path, "task-2", "Done")
    write_task(tmp_path, "task-3", "In Progress")
    assert built.writer is not None and built.edit is not None

    assert built.writer("task-1", "Done", "operator").ok
    built.writer("task-1", "In Progress", "operator")
    assert built.edit("task-1", {"dependencies": ["task-2", "task-3"]}, "").ok
    assert not built.writer("task-1", "Done", "operator").ok
    assert built.edit("task-1", {"dependencies": ["task-2", "task-9"]}, "").ok
    assert not built.writer("task-1", "Done", "operator").ok  # a dependency with no file is in no state
    assert built.edit("task-1", {"dependencies": []}, "").ok
    assert built.writer("task-1", "Done", "operator").ok  # none to wait for
    assert "status: Done\n" in path.read_text()


def test_a_dependency_in_any_of_the_named_states_satisfies_all_in(tmp_path: Path) -> None:
    path, built = ruled(
        tmp_path, [done_needs({"dependencies": {"all_in": ["Done", "Review"]}})], dependencies="[task-2]"
    )
    write_task(tmp_path, "task-2", "Review")
    assert built.writer is not None

    assert built.writer("task-1", "Done", "operator").ok


CHECKLISTS = (
    "\n## Acceptance Criteria\n<!-- AC:BEGIN -->\n- [x] #1 one\n- [{ac}] #2 two\n<!-- AC:END -->\n"
    "\n## Definition of Done\n<!-- DOD:BEGIN -->\n- [{dod}] #1 docs\n<!-- DOD:END -->\n"
)


@pytest.mark.parametrize(
    ("sections", "ac", "dod", "expected"),
    [
        (["acceptance_criteria"], "x", " ", True),
        (["acceptance_criteria"], " ", "x", False),
        (["acceptance_criteria", "definition_of_done"], "x", "x", True),
        (["acceptance_criteria", "definition_of_done"], "x", " ", False),
        (["definition_of_done"], " ", "x", True),
    ],
)
def test_a_checklist_primitive_holds_when_every_item_of_the_named_lists_is_checked(
    tmp_path: Path, sections: list[str], ac: str, dod: str, expected: bool
) -> None:
    require = {"checklist": {"sections": sections, "all_checked": True}}

    assert lands(tmp_path, require, CHECKLISTS.format(ac=ac, dod=dod)) is expected


def test_a_checklist_rule_judges_the_list_as_the_same_write_leaves_it(tmp_path: Path) -> None:
    require = {"checklist": {"sections": ["acceptance_criteria"], "all_checked": True}}
    path, built = ruled(tmp_path, [done_needs(require)])
    path.write_text(path.read_text() + CHECKLISTS.format(ac=" ", dod="x"))
    assert built.edit is not None

    done = {"status": "Done", "acceptanceCriteria": [{"n": 1, "text": "one", "checked": True}]}
    assert not built.edit("task-1", {"status": "Done"}, "").ok
    assert built.edit(
        "task-1",
        {
            **done,
            "acceptanceCriteria": [{"n": 1, "text": "one", "checked": True}, {"n": 2, "text": "two", "checked": True}],
        },
        "",
    ).ok


@pytest.mark.parametrize(
    ("require", "complaint"),
    [
        ({"any_of": []}, "any_of"),
        ({"any_of": [{"colour": {}}]}, r"any_of.*colour"),
        ({"label": {}}, "label"),
        ({"label": {"contains": "a", "prefix": "b"}}, "label"),
        ({"label": {"prefix": "size-"}}, "label"),
        ({"section": {"nonempty": True}}, "heading"),
        ({"section": {"heading": "Notes"}, "extra": {}}, "primitive"),
        ({"section": {"heading": "Notes", "except_self": True}}, "except_self"),
        ({"section": {"heading": "Notes", "not_matching": "("}}, "not_matching"),
        ({"dependencies": {}}, "all_in"),
        ({"dependencies": {"all_in": []}}, "all_in"),
        ({"checklist": {"sections": ["plan"], "all_checked": True}}, "plan"),
        ({"checklist": {"sections": ["acceptance_criteria"]}}, "all_checked"),
    ],
)
def test_a_primitive_the_board_cannot_read_is_a_startup_error_naming_it(
    tmp_path: Path, require: dict[str, Any], complaint: str
) -> None:
    board({}, tmp_path)

    with pytest.raises(ValueError, match=rf"rules\[0\].*{complaint}"):
        board({"rules": [done_needs(require)]}, tmp_path)


@pytest.mark.parametrize("actor", ["operator", "agent", "dagu/reconciler"])
def test_a_board_with_no_rule_set_accepts_every_move_between_its_lanes_as_it_did_before_rules(
    tmp_path: Path, actor: str
) -> None:
    built = board({}, tmp_path)
    path = write_task(tmp_path, "task-1", DEFAULT_STATUSES[0])
    assert built.writer is not None

    for lane in [*DEFAULT_STATUSES, *reversed(DEFAULT_STATUSES)]:
        assert built.writer("task-1", lane, actor).ok
        assert f"status: {lane}\n" in path.read_text()


def test_the_rules_a_config_files_board_tables_declare_reach_the_board(tmp_path: Path) -> None:
    (tmp_path / "starpulse.toml").write_text(
        """
[board]
type = "native"

[[board.rules]]
on = { to = "Done" }
require = { field = { field = "references", matches = "/pull/\\\\d+$", min = 1 } }
reason = "Done needs a pull request in references"
skill = "completing-tasks"
unless_actor = ["dagu/reconciler"]
"""
    )
    config = load(tmp_path / "starpulse.toml")
    board({}, tmp_path)
    path = write_task(tmp_path, "task-1", "In Progress")
    built = board(config.board, tmp_path)
    assert built.writer is not None

    assert built.writer("task-1", "Done", "agent") == (False, DONE_NEEDS_PR["reason"], "completing-tasks", False, "")
    assert built.writer("task-1", "Done", "dagu/reconciler").ok
    assert "status: Done\n" in path.read_text()
