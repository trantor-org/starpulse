"""A Cursor agent transcript read into the signals the session fold counts.

The fixture mirrors Cursor's on-disk layout (`agent-transcripts/<id>/<id>.jsonl` beside `compaction/segment_*.md`) with
scrubbed prompt and reply text; Cursor records no model, effort, token, tool result or per-line time.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from starpulse._internal.analytics import Analytics
from starpulse.contracts.adapters import TaskKeys
from starpulse.flow_metrics.session_health import session_health
from starpulse.harness_telemetry.cursor import CURSOR, transcript_signals

SESSION = "33333333-3333-4333-8333-333333333333"
TRANSCRIPT = Path(__file__).parents[2] / "fixtures/cursor/agent-transcripts" / SESSION / f"{SESSION}.jsonl"
KEYS = TaskKeys(key=re.compile(r"TASK-\d+"), branch=re.compile(r"(?:[\w.-]+/)*task-(\d+)"), key_format="TASK-{}")
ANALYTICS = Analytics(claims=(re.compile(r"board_task\.py\s+start\s+(TASK-\d+)"),))
MST = timezone(timedelta(hours=-7))


def test_a_transcript_is_a_cursor_session_row_for_the_task_it_claimed():
    found = transcript_signals(TRANSCRIPT, keys=KEYS, analytics=ANALYTICS)

    (row,) = session_health(found, KEYS, ANALYTICS)

    assert (row["harness"], row["session"], row["task"]) == (CURSOR, SESSION, "TASK-12")
    assert row["requests"] == 4
    assert row["tool_calls"] == 4
    assert row["tools"] == {"Shell": 2, "Read": 1, "StrReplace": 1}
    assert (row["main_model"], row["main_effort"], row["models"]) == (None, None, [])
    assert (row["prompts"], row["operator_prompts"]) == (3, 1)
    assert row["steps_before_edit"] == 3
    assert row["interrupts"] == 1
    assert row["compactions"] == {"unknown": 1}
    assert row["first_at"] == datetime(2026, 10, 11, 9, 52, tzinfo=MST).timestamp()
    assert (row["agent_s"], row["tokens"]["input"]) == (0.0, 0)


def test_a_cursor_signal_is_left_out_of_the_rankings():
    found = transcript_signals(TRANSCRIPT, keys=KEYS, analytics=ANALYTICS)

    assert found
    assert not any(s.captured for s in found)


def test_an_injected_prompt_is_labelled_and_its_text_is_never_kept():
    found = transcript_signals(TRANSCRIPT, keys=KEYS, analytics=ANALYTICS)

    prompts = [s for s in found if s.kind == "prompt"]

    assert [s.detail for s in prompts] == ["human", "injected", "human"]
    assert "start the next task" not in repr(found)


def test_a_shell_command_is_kept_only_through_a_redactor():
    bare = transcript_signals(TRANSCRIPT, keys=KEYS, analytics=ANALYTICS)
    redacted = transcript_signals(TRANSCRIPT, keys=KEYS, analytics=ANALYTICS, redact=str.upper)

    assert {s.command for s in bare} == {""}
    assert "GIT STATUS --SHORT" in {s.command for s in redacted}


def test_reading_a_transcript_twice_gives_the_same_keys():
    first = transcript_signals(TRANSCRIPT, keys=KEYS, analytics=ANALYTICS)
    second = transcript_signals(TRANSCRIPT, keys=KEYS, analytics=ANALYTICS)

    assert [s.key for s in first] == [s.key for s in second]
    assert len({s.key for s in first}) == len(first)
