"""A kind or housekeeping step a project declares as a command in its StarPulse config."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from starpulse.sweeper.passes import Outcome


def _run(name: str, command: list[str], base: Path, timeout_s: float) -> str:
    """The stdout of `command` run in `base`. Raises `RuntimeError` naming `name` when it fails, times out or is not found."""
    try:
        done = subprocess.run(command, cwd=base, capture_output=True, text=True, timeout=timeout_s, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"{name}: {exc}") from exc
    if done.returncode:
        raise RuntimeError(f"{name}: exit {done.returncode}: {done.stderr.strip()[-200:]}")
    return done.stdout


def _count(name: str, value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"{name}: {key} is not a count: {value!r}")
    return value


class CommandKind:
    """A kind whose `command` prints, on its last line, its corrections as a count (`3`) or as
    `{"corrected": 3, "sampled": 8}`."""

    def __init__(self, name: str, command: list[str], base: Path, timeout_s: float) -> None:
        self.name = name
        self._args = (command, base, timeout_s)

    def run(self) -> Outcome:
        lines = _run(self.name, *self._args).strip().splitlines()
        try:
            printed = json.loads(lines[-1])
        except (IndexError, ValueError):
            raise RuntimeError(f"{self.name}: printed no count") from None
        if isinstance(printed, dict) and "corrected" in printed:
            sampled = printed.get("sampled", 0)
            return Outcome(_count(self.name, printed["corrected"], "corrected"), _count(self.name, sampled, "sampled"))
        return Outcome(_count(self.name, printed, "count"))


class CommandHousekeeping:
    """A housekeeping step that runs `command` and reads nothing back; a non-zero exit is its failure."""

    def __init__(self, name: str, command: list[str], base: Path, timeout_s: float) -> None:
        self.name = name
        self._args = (command, base, timeout_s)

    def run(self) -> None:
        _run(self.name, *self._args)
