"""The built-in session starter: what the scheduler starts a task's session with when no `session_start_url` is set.

It opens the configured harness's launch command in a detached tmux session named for the task, in the config's directory, so a fresh
`starpulse serve` board needs no start service. It uses the default model and effort; a deployment that routes a task to
its assignee's profile sets `session_start_url` instead.
"""

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starpulse.contracts.adapters import StartFailedError
from starpulse.sessions.ports.harness import SessionHarness


def builtin_starter(
    cwd: Path,
    adapter: SessionHarness,
    run: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> Callable[..., str]:
    """Start a task's session in a detached tmux session started in `cwd` and answer `tmux:<session name>`.

    A missing `tmux` or the adapter's binary, or a tmux that exits non-zero, raises `StartFailedError` naming the cause. It starts
    only the configured harness: another `harness` raises `StartFailedError` naming `session_start_url`, the seam that dispatches one.
    `mode` is accepted so the seam matches `session_start_url` and ignored. `verb` is the prompt's verb (`Start`, or
    `Verify` for the verify lane) and `profile` the agent profile a verify session runs on, passed as `--agent`.
    """

    def start(
        task: str, *, harness: str | None = None, mode: str = "interactive", verb: str = "Start", profile: str | None = None
    ) -> str:
        _ = mode
        if harness not in (None, adapter.name):
            raise StartFailedError(
                f"the built-in starter starts only {adapter.name}; set session_start_url to start {harness}"
            )
        launch = adapter.launch(task, verb, profile)
        if missing := next((name for name in ("tmux", launch[0]) if which(name) is None), None):
            raise StartFailedError(f"the built-in starter needs {missing} on PATH")
        name = f"starpulse-{task}"
        argv = ["tmux", "new-session", "-d", "-s", name, "-c", str(cwd), *launch]
        done = run(argv, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise StartFailedError(f"tmux could not start {name}: {done.stderr.strip() or f'exit {done.returncode}'}")
        return f"tmux:{name}"

    return start
