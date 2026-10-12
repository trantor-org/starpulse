"""The `[analytics]` table: what the instance's agents' telemetry is read against, and a table it cannot read is refused."""

import re
from pathlib import Path

import pytest

from starpulse._internal.config.analytics import Analytics, MachineStage, SkillLoad, SkillMachine
from starpulse._internal.config.config import ConfigError, load


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return path


def test_no_table_declares_nothing(tmp_path: Path) -> None:
    assert load(None).analytics == load(_write(tmp_path, "")).analytics == Analytics()


def test_a_table_declares_the_roots_the_stops_and_the_skills_triggers(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[analytics]
roots = ["/repo", "/repo/.claude/worktrees/*"]
stop_activities = ["ScheduleWakeup", "bin/backlog_task.py"]
lifecycle_skills = ["starting-tasks"]

[[analytics.skill_loads]]
skill = "operating-unraid"
activities = ["ssh *@unraid"]

[[analytics.skill_loads]]
skill = "verifying-claims"
title = "^(validate|verify)"
label = "validation"
""",
    )

    assert load(path).analytics == Analytics(
        roots=("/repo", "/repo/.claude/worktrees/*"),
        stop_activities=frozenset({"ScheduleWakeup", "bin/backlog_task.py"}),
        lifecycle_skills=frozenset({"starting-tasks"}),
        skill_loads=(
            SkillLoad("operating-unraid", activities=frozenset({"ssh *@unraid"})),
            SkillLoad("verifying-claims", title=re.compile("^(validate|verify)", re.IGNORECASE), label="validation"),
        ),
    )


def test_a_table_declares_how_a_session_is_read_for_its_turns_claims_and_completion(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        r"""
[analytics]
injected_openings = ["<task-notification", "[board-autopilot]"]
operator_tools = ["AskUserQuestion", "ExitPlanMode"]
claims = ['backlog_task\.py\s+start\s+(TASK-\d+)', '^\s*(TASK-\d+)\s*$']
completion_skill = "completing-tasks"
completion_call = 'backlog_task\.py\s+deliver\b'
""",
    )

    analytics = load(path).analytics

    assert analytics.injected_openings == ("<task-notification", "[board-autopilot]")
    assert analytics.operator_tools == frozenset({"AskUserQuestion", "ExitPlanMode"})
    assert [c.pattern for c in analytics.claims] == [r"backlog_task\.py\s+start\s+(TASK-\d+)", r"^\s*(TASK-\d+)\s*$"]
    assert analytics.completion_skill == "completing-tasks"
    assert analytics.completion_call is not None
    assert analytics.completion_call.search("bin/backlog_task.py deliver --task 1")


def test_a_table_declares_the_stages_a_run_reaches_in_order_to_conform_to_a_skills_machine(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[analytics.skill_machines]]
skill = "developing-test-first"
stages = [
  { name = "RED", activities = ["pytest", "make test*"], ok = false },
  { name = "GREEN", activities = ["pytest", "make test*"], ok = true },
  { name = "REFACTOR", activities = ["make lint"] },
]
""",
    )

    assert load(path).analytics.skill_machines == (
        SkillMachine(
            "developing-test-first",
            (
                MachineStage("RED", frozenset({"pytest", "make test*"}), ok=False),
                MachineStage("GREEN", frozenset({"pytest", "make test*"}), ok=True),
                MachineStage("REFACTOR", frozenset({"make lint"})),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("table", "refusal"),
    [
        ('analytics = "x"', "analytics must be an [analytics] table"),
        ("[analytics]\nroot = []", "analytics: unknown key(s) root"),
        ("[analytics]\nroots = [1]", "analytics: roots must be a list of text"),
        ('[analytics]\nstop_activities = "a"', "analytics: stop_activities must be a list of text"),
        ('[analytics]\nroots = ["relative"]', "analytics: roots must be absolute paths"),
        ("[[analytics.skill_loads]]\nlabel = 'x'", "analytics.skill_loads[0] needs skill"),
        ("[[analytics.skill_loads]]\nskill = 'x'", "analytics.skill_loads[0]: needs activities, title or label"),
        (
            "[[analytics.skill_loads]]\nskill = 'x'\ntitle = '('",
            "analytics.skill_loads[0]: title is not a regular expression",
        ),
        ('[analytics]\ninjected_openings = [1]', "analytics: injected_openings must be a list of text"),
        ('[analytics]\noperator_tools = "a"', "analytics: operator_tools must be a list of text"),
        ('[analytics]\nclaims = ["("]', "analytics: claims[0] is not a regular expression"),
        ('[analytics]\nclaims = ["TASK-\\\\d+"]', "analytics: claims[0] needs a group that captures the task key"),
        ("[analytics]\ncompletion_skill = 1", "analytics: completion_skill must be text"),
        ('[analytics]\ncompletion_call = "("', "analytics: completion_call is not a regular expression"),
        ("[[analytics.skill_machines]]\nstages = []", "analytics.skill_machines[0] needs skill"),
        ("[[analytics.skill_machines]]\nskill = 'x'", "analytics.skill_machines[0]: needs stages"),
        (
            "[[analytics.skill_machines]]\nskill = 'x'\nstages = [{ activities = ['a'] }]",
            "analytics.skill_machines[0].stages[0] needs name",
        ),
        (
            "[[analytics.skill_machines]]\nskill = 'x'\nstages = [{ name = 'n' }]",
            "analytics.skill_machines[0].stages[0]: needs activities",
        ),
        (
            "[[analytics.skill_machines]]\nskill = 'x'\nstages = [{ name = 'n', activities = ['a'], ok = 'no' }]",
            "analytics.skill_machines[0].stages[0]: ok must be true or false",
        ),
        (
            "[[analytics.skill_machines]]\nskill = 'x'\nstages = [{ name = 'n', activities = ['a'], when = 1 }]",
            "analytics.skill_machines[0].stages[0]: unknown key(s) when",
        ),
        (
            "[[analytics.skill_loads]]\nskill = 'x'\nlabel = 'l'\nwhen = 1",
            "analytics.skill_loads[0]: unknown key(s) when",
        ),
    ],
)
def test_a_table_the_view_cannot_read_is_refused_naming_the_key(tmp_path: Path, table: str, refusal: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(refusal)):
        load(_write(tmp_path, table))
