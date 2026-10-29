"""Runs the configured take-over command for a task, flipping its unattended workflow to interactive.

The command is engine-neutral: StarPulse appends the task id to the configured argv and reads the exit status, so the
workflow engine stays in the command.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence

#: The exit status that says the task has no running workflow (an attended task).
NO_WORKFLOW = 1
#: Seconds the command may take before the take-over fails.
TIMEOUT_S = 60


def command_take_over(argv: Sequence[str]) -> Callable[[str], bool]:
    """A `take_over(task)` that runs `argv` with the task appended: True on exit 0, False on exit 1, else raises."""

    def take_over(task: str) -> bool:
        proc = subprocess.run([*argv, task], capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
        if proc.returncode == 0:
            return True
        if proc.returncode == NO_WORKFLOW:
            return False
        raise RuntimeError(f"take-over command exited {proc.returncode}: {proc.stderr.strip()[-500:]}")

    return take_over
