"""The built-in session starter: what the autopilot starts a task's session with when no `session_start_url` is set.

It opens `claude --remote-control` in a detached tmux session named for the task, in the config's directory, so a fresh
`starpulse serve` board needs no start service. It uses the default model and effort; a deployment that routes a task to
its assignee's profile sets `session_start_url` instead.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starpulse.contracts.adapters import StartFailedError

#: The binaries a session needs on `PATH`.
_BINARIES = ("tmux", "claude")


def builtin_starter(
    cwd: Path,
    run: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> Callable[[str], str]:
    """Start a task's session in a detached tmux session started in `cwd` and answer `tmux:<session name>`.

    A missing `tmux` or `claude`, or a tmux that exits non-zero, raises `StartFailedError` naming the cause.
    """

    def start(task: str) -> str:
        if missing := next((name for name in _BINARIES if which(name) is None), None):
            raise StartFailedError(f"the built-in starter needs {missing} on PATH")
        name = f"starpulse-{task}"
        argv = ["tmux", "new-session", "-d", "-s", name, "-c", str(cwd), "claude", "--remote-control", task, f"Start {task}"]
        done = run(argv, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise StartFailedError(f"tmux could not start {name}: {done.stderr.strip() or f'exit {done.returncode}'}")
        return f"tmux:{name}"

    return start
