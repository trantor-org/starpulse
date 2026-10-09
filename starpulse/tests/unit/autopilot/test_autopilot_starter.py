"""The built-in starter: with no `session_start_url`, a task's session is `claude --remote-control` in a tmux session."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from starpulse._internal.autopilot.starter import builtin_starter
from starpulse.contracts.adapters import StartFailedError


class Rig:
    """A starter whose process runner and binary lookup the test sets."""

    def __init__(self, tmp_path: Path, missing: tuple[str, ...] = (), returncode: int = 0, stderr: str = "") -> None:
        self.ran: list[list[str]] = []
        self.returncode, self.stderr = returncode, stderr

        def run(argv: list[str], **_: Any) -> Any:
            self.ran.append(argv)
            return SimpleNamespace(returncode=self.returncode, stderr=self.stderr)

        self.start = builtin_starter(
            tmp_path, run=run, which=lambda name: None if name in missing else f"/usr/bin/{name}"
        )


def test_a_task_starts_as_claude_remote_control_in_a_detached_tmux_session(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    session = rig.start("TASK-7")

    assert rig.ran == [
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            "starpulse-TASK-7",
            "-c",
            str(tmp_path),
            "claude",
            "--remote-control",
            "TASK-7",
            "Start TASK-7",
        ]
    ]
    assert session == "tmux:starpulse-TASK-7"


@pytest.mark.parametrize("binary", ["tmux", "claude"])
def test_a_missing_binary_refuses_the_start_naming_it(tmp_path: Path, binary: str) -> None:
    rig = Rig(tmp_path, missing=(binary,))

    with pytest.raises(StartFailedError, match=binary):
        rig.start("TASK-7")

    assert rig.ran == []


def test_a_tmux_that_fails_refuses_the_start_with_its_message(tmp_path: Path) -> None:
    rig = Rig(tmp_path, returncode=1, stderr="duplicate session: starpulse-TASK-7")

    with pytest.raises(StartFailedError, match="duplicate session"):
        rig.start("TASK-7")
