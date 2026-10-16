"""A Cursor session's context use, read from the percent its agent pane footer shows."""

from starpulse._internal.harnesses.cursor_context import context_tokens, cursor_task_sessions

PANE = """\
  ⏺ Read lib/x.py

  Next step: run the tests.

 → Add a follow-up
  Auto  60.3%
"""


def test_the_footer_percent_of_a_window_is_the_context_tokens():
    assert context_tokens(PANE, 200_000) == 120_600


def test_a_pane_without_a_footer_percent_has_no_reading():
    assert context_tokens("  ⏺ Read lib/x.py\n 50% of files matched\n  ⏵ done\n", 200_000) is None


PANES = "task-12 100\ntask-13 200\nscratch 300\ntask-14 400\ntask-15 500\n"
PROCESSES = (
    "  PID  PPID ARGS\n"
    "  100     1 bash -c run\n"
    "  101   100 /home/u/.local/bin/cursor-agent --model composer-2.5 --force Start TASK-12\n"
    "  200     1 -bash\n"
    "  201   200 claude --resume abc\n"
    "  202   201 grep -rn cursor-agent docs\n"
    "  300     1 cursor-agent\n"
    "  400     1 -bash\n"
    "  401   400 agent --force Start TASK-14\n"
    "  500     1 -bash\n"
    "  501   500 node /x/agent --force\n"
)


def test_only_task_sessions_with_a_cursor_agent_in_their_process_tree_are_cursor_sessions() -> None:
    assert cursor_task_sessions(PANES, PROCESSES) == ["task-12", "task-14"]
