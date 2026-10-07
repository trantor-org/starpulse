"""The checks behind `starpulse doctor`, each reported as pass or fail with why.

The checks cover config loading, the server, each configured adapter, and the GitHub CLI. One failure never stops the
others, so a report names every fault at once.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from starpulse.config import Config

#: Seconds a `gh` command may take.
_COMMAND_TIMEOUT = 10


@dataclass(frozen=True)
class Probes:
    """What the checks touch outside the process: installed tools and commands."""

    which: Callable[[str], str | None]
    run: Callable[..., subprocess.CompletedProcess[str]]


LIVE = Probes(
    which=shutil.which,
    run=subprocess.run,
)


def _result(check: str, ok: bool, reason: str) -> dict[str, str]:
    return {"check": check, "status": "pass" if ok else "fail", "reason": reason}


def _command(probes: Probes, *argv: str) -> tuple[int, str]:
    """The exit code and trimmed output of `argv`; a command that cannot finish is a failure with its reason."""
    try:
        done = probes.run(list(argv), capture_output=True, text=True, check=False, timeout=_COMMAND_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout.strip() if done.returncode == 0 else done.stderr.strip())


def _adapters(snapshot: dict[str, Any] | str, config: Config | str) -> list[dict[str, str]]:
    """One result per producer: the Board, then each configured runs instance that pulls (a push-only one has no adapter)."""
    instances = [] if isinstance(config, str) else [i.name for i in config.runs if i.type]
    if isinstance(snapshot, str):
        return [_result(f"adapter:{name}", False, "the server is unreachable") for name in ["board", *instances]]
    errors = (snapshot["error"] or "").split("; ")
    board = next(flow for flow in snapshot["flows"] if flow["name"] == "board")
    found = [_board(board, errors)]
    for name in instances:
        error = next((e for e in errors if e.startswith(f"{name}: ")), None)
        listed = sum(dag["name"].startswith(f"{name}/") for dag in snapshot["dags"])
        if error:
            found.append(_result(f"adapter:{name}", False, error))
        elif not listed:
            found.append(_result(f"adapter:{name}", False, f"{name} lists no workflows"))
        else:
            found.append(_result(f"adapter:{name}", True, f"{name} lists {listed} workflows"))
    return found


def _board(board: dict[str, Any], errors: list[str]) -> dict[str, str]:
    if reading := next((e for e in errors if e.startswith("board: ")), None):
        return _result("adapter:board", False, reading)
    return _result("adapter:board", True, f"{len(board['agents'])} open tasks")


def _gh(probes: Probes) -> dict[str, str]:
    if not probes.which("gh"):
        return _result("gh", False, "gh is not installed, so a task's pull requests carry no state")
    code, text = _command(probes, "gh", "auth", "status")
    if code != 0:
        return _result("gh", False, f"gh auth status failed: {text}; run `gh auth login`")
    return _result("gh", True, "gh is logged in")


def run_checks(
    snapshot: dict[str, Any] | str, config: Config | str, probes: Probes, server: str
) -> dict[str, Any]:
    """Every check as `{ok, checks: [{check, status, reason}]}`.

    `snapshot` is the server's snapshot, or the reason it could not be read; `config` is the loaded config, or the
    reason it could not be loaded; `server` is the address the snapshot was read from."""
    checks = [
        _result(
            "config", *((False, config) if isinstance(config, str) else (True, f"{len(config.runs)} runs instances"))
        ),
        _result("server", *((False, snapshot) if isinstance(snapshot, str) else (True, f"{server} answers"))),
        *_adapters(snapshot, config),
        _gh(probes),
    ]
    return {"ok": all(c["status"] == "pass" for c in checks), "checks": checks}
