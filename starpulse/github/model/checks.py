"""Check deliveries as per-check reports, and a head's rollup against the base ruleset's required checks.

A report is one check's state on one commit: `passed`, `failing` or `pending`. A rollup reads every required check of
the base branch's rules on the current head: a required check that has posted nothing is `pending`, never green.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ["FAILED", "PASSED", "Report", "dict_of", "report_of", "required_of", "results_of", "rollup"]

#: The conclusions of a completed check run that count as a pass, and as a failure; any other leaves it pending.
PASSED = frozenset({"success", "neutral", "skipped"})
FAILED = frozenset({"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale"})
_STATUS = {"success": "passed", "pending": "pending", "failure": "failing", "error": "failing"}
_WORST = ("failing", "pending", "passed")


@dataclass(frozen=True)
class Report:
    """One check's `state` on commit `sha`; `key` names the delivery's record and state, so a redelivery repeats it."""

    repository: str
    sha: str
    name: str
    state: str
    key: str
    pulls: tuple[int, ...] = ()


def dict_of(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _run_state(status: object, conclusion: object) -> str:
    if status != "completed":
        return "pending"
    return "passed" if conclusion in PASSED else "failing" if conclusion in FAILED else "pending"


def report_of(event: str, body: bytes) -> Report | None:
    """The check a `check_run`, `check_suite` or `status` delivery reports, read from its body alone."""
    try:
        payload = dict_of(json.loads(body))
    except ValueError:
        return None
    repository = _text(dict_of(payload.get("repository")).get("full_name"))
    if event == "status":
        sha, name, raw = _text(payload.get("sha")), _text(payload.get("context")), _text(payload.get("state"))
        state, key, pulls = _STATUS.get(raw), f"{payload.get('id')}:{raw}", ()
    elif event in ("check_run", "check_suite"):
        thing = dict_of(payload.get(event))
        sha, status, conclusion = _text(thing.get("head_sha")), thing.get("status"), thing.get("conclusion")
        name = _text(thing.get("name")) if event == "check_run" else _text(dict_of(thing.get("app")).get("slug"))
        state, key = _run_state(status, conclusion), f"{thing.get('id')}:{status}:{conclusion}"
        listed = thing.get("pull_requests")
        pulls = tuple(n for item in listed if isinstance(n := dict_of(item).get("number"), int)) if isinstance(listed, list) else ()
    else:
        return None
    return Report(repository, sha, name, state, key, pulls) if repository and sha and name and state else None


def required_of(rules: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    """The contexts the branch rules (`GET /repos/{r}/rules/branches/{b}`) require, across every status-check rule."""
    return frozenset(
        _text(check.get("context"))
        for rule in rules
        if rule.get("type") == "required_status_checks"
        for check in dict_of(rule.get("parameters")).get("required_status_checks") or []
    )


def results_of(runs: Iterable[Mapping[str, Any]], statuses: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """Each posted check's state by name, from a head's check runs and commit statuses; the worse of two of one name."""
    seen = [(_text(r.get("name")), _run_state(r.get("status"), r.get("conclusion"))) for r in runs]
    seen += [(_text(s.get("context")), _STATUS.get(_text(s.get("state")), "pending")) for s in statuses]
    results: dict[str, str] = {}
    for name, state in seen:
        if name not in results or _WORST.index(state) < _WORST.index(results[name]):
            results[name] = state
    return results


def rollup(required: frozenset[str], results: Mapping[str, str]) -> str:
    """`passed` when every required check passed (or none is required), `failing` on any failure, else `pending`."""
    states = {results.get(name, "pending") for name in required}
    return "failing" if "failing" in states else "pending" if "pending" in states else "passed"
