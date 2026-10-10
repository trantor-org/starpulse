"""The `[analytics]` table: what the instance's agents' telemetry is read against, and a table it cannot read is refused."""

import re
from pathlib import Path

import pytest

from starpulse._internal.config.analytics import Analytics, SkillLoad
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
        (
            "[[analytics.skill_loads]]\nskill = 'x'\nlabel = 'l'\nwhen = 1",
            "analytics.skill_loads[0]: unknown key(s) when",
        ),
    ],
)
def test_a_table_the_view_cannot_read_is_refused_naming_the_key(tmp_path: Path, table: str, refusal: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(refusal)):
        load(_write(tmp_path, table))
