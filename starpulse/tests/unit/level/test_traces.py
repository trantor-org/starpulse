"""Cases and the skills they missed: folds of harness telemetry signals, worked out by hand."""

import re

from starpulse._internal.config.analytics import SkillLoad
from starpulse._internal.level.traces import Case, Missed, cases, missed_loads
from starpulse.tests.unit.level.test_sessions import KEYS, T0, sig

ROOTS = ["/r", "/r/.claude/worktrees/*"]


def tool(at: float, *activities: str, reads: tuple[str, ...] = (), writes: tuple[str, ...] = (), **kw: object):
    return sig(
        "tool", at, name=activities[0] if activities else "", activities=activities, reads=reads, writes=writes, **kw
    )


def test_a_session_task_is_one_case_with_its_work_in_order() -> None:
    found = [
        sig("start", 0, branch="claude/task-7-x"),
        tool(1, "git status", "make test"),
        sig("skill", 2, name="verifying-claims"),
        tool(3, "Read", reads=("/r/lib/a/b/c.py",)),
        tool(4, "Edit", writes=("/r/.claude/worktrees/t7/docs/x.md",)),
        tool(5, "Read", reads=("/elsewhere/f", "/r/lib/a/other.py")),
    ]

    [case] = cases(found, KEYS, roots=ROOTS, tasks={"TASK-7": {"title": "Verify x", "labels": ["validation"]}})

    assert (case.task, case.tool_calls, case.last_seen) == ("TASK-7", 4, T0 + 5)
    assert case.activities == ("git status", "make test", "Read", "Edit", "Read")
    assert case.skills == ("verifying-claims",)
    assert (case.reads, case.writes) == (("lib/a",), ("docs/x.md",))
    assert (case.title, case.labels) == ("Verify x", ("validation",))


def test_a_tool_signal_stored_before_activities_were_kept_is_its_tool_name() -> None:
    [case] = cases([sig("start", 0), sig("tool", 1, name="Bash")], KEYS)

    assert (case.task, case.tool_calls, case.activities) == (None, 1, ("Bash",))


def test_a_branch_switch_starts_a_case_for_the_task_it_names() -> None:
    found = [
        sig("start", 0, branch="claude/task-1-a"),
        tool(1, "make fmt"),
        sig("branch", 2, name="claude/task-2-b"),
        tool(3, "make test"),
    ]

    assert [(c.task, c.activities) for c in cases(found, KEYS)] == [
        ("TASK-1", ("make fmt",)),
        ("TASK-2", ("make test",)),
    ]


def test_a_case_that_ran_a_triggers_work_without_loading_its_skill_is_missed() -> None:
    triggers = [
        SkillLoad("operating-unraid", activities=frozenset({"ssh *@unraid"})),
        SkillLoad("verifying-claims", title=re.compile(r"^verify", re.IGNORECASE), label="validation"),
    ]
    found = [
        sig("start", 0, session="a", branch="claude/task-1-a"),
        tool(1, "ssh root@unraid", session="a"),
        sig("start", 0, session="b", branch="claude/task-2-b"),
        tool(1, "ssh root@unraid", session="b"),
        sig("skill", 2, session="b", name="operating-unraid"),
        sig("start", 0, session="c", branch="claude/task-3-c"),
        tool(1, "make test", session="c"),
        sig("start", 0, session="d", branch="claude/task-4-d"),
        sig("prompt", 1, session="d"),
    ]
    tasks = {"TASK-3": {"title": "Verify the thing", "labels": []}, "TASK-4": {"title": "Verify nothing", "labels": []}}

    unraid, verifying = missed_loads(cases(found, KEYS, tasks=tasks), triggers)

    assert (unraid.skill, [c.session for c in unraid.performed], [c.session for c in unraid.missed]) == (
        "operating-unraid",
        ["a", "b"],
        ["a"],
    )
    # a task shape counts only for a case with a trace: session d did no tool call.
    assert (verifying.skill, [c.session for c in verifying.performed], [c.session for c in verifying.missed]) == (
        "verifying-claims",
        ["c"],
        ["c"],
    )
    assert isinstance(unraid, Missed) and isinstance(unraid.performed[0], Case)
