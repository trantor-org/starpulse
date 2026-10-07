"""A task's Start Criteria on its record: parsed from the description, evaluated by the `[board] criteria` command.

The description's `## Start Criteria` section holds a fenced YAML block, `start_criteria:` a list of criteria each with
an `id`, a `kind`, the expression it tests (`query`, `expr` or `path`) and a threshold (`at_least`, `at_most`, `equals`
or `since`). The `criteria` command is run with `{id}` replaced by the task's id and prints a JSON array, one object per
criterion, with its `id`, `status` (`met`, `not-met` or `error`), `observed`, `error` and `checked_at`; it exits non-zero
when a criterion is unmet, so its output is read whatever its exit status. A failed command never fails the record: it
marks every criterion `error`.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

__all__ = ["CACHE_SECONDS", "TIMEOUT", "Evaluator", "authored"]

#: Seconds the evaluator command may run before every criterion is marked `error`.
TIMEOUT = 10.0
#: Seconds a task's evaluated criteria are reused before the command runs again.
CACHE_SECONDS = 30.0
_clock = time.monotonic

_SECTION = re.compile(r"^## Start Criteria\s*$(.*?)(?=^## |\Z)", re.M | re.S)
_FENCE = re.compile(r"```ya?ml\s*\n(.*?)```", re.S)
_THRESHOLDS = ("at_least", "at_most", "equals", "since")
_STATUS = {"not-met": "unmet"}
NOT_EVALUATED = "not evaluated"


def authored(description: str) -> list[dict[str, Any]]:
    """The criteria the description's `start_criteria` block declares, as `{id, kind, expr, cmp, want}`; empty when it has none."""
    section = _SECTION.search(description)
    fenced = _FENCE.search(section.group(1)) if section else None
    try:
        parsed = yaml.safe_load(fenced.group(1)) if fenced else None
    except yaml.YAMLError:
        return []
    listed = parsed.get("start_criteria") if isinstance(parsed, dict) else None
    found = []
    for raw in listed if isinstance(listed, list) else []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        cmp = next((key for key in _THRESHOLDS if key in raw), None)
        found.append(
            {
                "id": str(raw["id"]),
                "kind": str(raw.get("kind") or ""),
                "expr": str(raw.get("query") or raw.get("expr") or raw.get("path") or ""),
                "cmp": cmp,
                "want": raw[cmp] if cmp else None,
            }
        )
    return found


def _outcome(status: str, observed: Any = None, error: str | None = None, checked: str | None = None) -> dict[str, Any]:
    return {"status": status, "observed": observed, "error": error, "checked": checked}


def _failed(criteria: list[dict[str, Any]], message: str) -> list[dict[str, Any]]:
    return [{**criterion, **_outcome("error", error=message)} for criterion in criteria]


def _run(command: list[str], cwd: Path, criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each criterion with the status the command printed for it, or `error` with why the command gave none."""
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return _failed(criteria, f"{shlex.join(command)}: timed out after {TIMEOUT:g}s")
    except OSError as error:
        return _failed(criteria, f"{shlex.join(command)}: {error}")
    try:
        printed = json.loads(done.stdout)
    except ValueError:
        printed = None
    if not isinstance(printed, list):
        said = done.stderr.strip() or done.stdout.strip() or "printed no JSON"
        return _failed(criteria, f"{shlex.join(command)}: exit {done.returncode}: {said}")
    results = {item["id"]: item for item in printed if isinstance(item, dict) and "id" in item}
    return [
        {
            **criterion,
            **(
                _outcome(
                    _STATUS.get(str(item.get("status")), str(item.get("status"))),
                    item.get("observed"),
                    item.get("error"),
                    item.get("checked_at"),
                )
                if (item := results.get(criterion["id"]))
                else _outcome("error", error=f"the evaluator returned no result for {criterion['id']}")
            ),
        }
        for criterion in criteria
    ]


class Evaluator:
    """Evaluates a task's criteria with `command`, run in `cwd`, reusing a task's result for `CACHE_SECONDS`."""

    def __init__(self, command: str, cwd: Path) -> None:
        self._command = shlex.split(command)
        self._cwd = cwd
        self._cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}
        self._lock = threading.Lock()

    def __call__(self, task: str, description: str) -> list[dict[str, Any]]:
        criteria = authored(description)
        if not criteria:
            return []
        key = (task, json.dumps(criteria, sort_keys=True, default=str))
        with self._lock:
            if (cached := self._cache.get(key)) and _clock() - cached[0] < CACHE_SECONDS:
                return cached[1]
            command = [part.replace("{id}", task) for part in self._command]
            evaluated = _run(command, self._cwd, criteria)
            self._cache[key] = (_clock(), evaluated)
            return evaluated


def evaluator(command: object, cwd: Path) -> Callable[[str, str], list[dict[str, Any]]]:
    """The function that gives a task's criteria their results: `command` evaluates them, or none does and each is `not evaluated`."""
    if command:
        return Evaluator(str(command), cwd)
    return lambda task, description: [{**c, **_outcome(NOT_EVALUATED)} for c in authored(description)]
