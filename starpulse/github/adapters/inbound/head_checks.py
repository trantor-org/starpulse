"""A check or pull request delivery as the `pr-checks` events of its head: each check's report and the head's rollup.

`HeadChecks.plan` reads what a delivery alone cannot say (the open pull requests of its commit, the base branch's
required checks, every check posted on the head) and returns the events to publish. The required set is cached per
base branch and read again on each `pull_request` delivery, so a ruleset is never polled. A head's rollup is published
only when its state changes, and only for a pull request that is not a draft.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from starpulse.github.model.checks import Report, dict_of, report_of, rollup
from starpulse.github.model.events import SOURCE
from starpulse.github.ports.events import Head, Links, Reader

__all__ = ["HeadChecks", "Plan"]

MACHINE = "pr-checks"
#: The `pull_request` actions that move a head or make it ready, and so call for a fresh rollup.
_HEAD_MOVED = frozenset({"opened", "reopened", "synchronize", "ready_for_review"})
_FINAL = frozenset({"passed", "failing"})


@dataclass(frozen=True)
class Plan:
    """The `events` to post for a delivery; `settle` records that the rollups among them were posted."""

    events: list[dict[str, Any]]
    settle: Callable[[], None]


def _event(kind: str, task: str, identity: tuple[object, ...], data: dict[str, Any]) -> dict[str, Any]:
    digest = hashlib.sha256("\0".join(map(str, (kind, *identity))).encode()).hexdigest()
    return {
        "specversion": "1.0",
        "id": f"{SOURCE}:{MACHINE}:{digest[:40]}",
        "source": SOURCE,
        "type": kind,
        "subject": task,
        "machine": MACHINE,
        "actor": SOURCE,
        "data": data,
    }


def _moved_head(event: str, body: bytes) -> tuple[str, str, Head, str] | None:
    """`(repository, sha, head, action)` of a `pull_request` delivery that moves or readies a head, else None."""
    try:
        payload = dict_of(json.loads(body))
    except ValueError:
        return None
    action, pull = payload.get("action"), dict_of(payload.get("pull_request"))
    repository = dict_of(payload.get("repository")).get("full_name")
    sha, base, number = dict_of(pull.get("head")).get("sha"), dict_of(pull.get("base")).get("ref"), pull.get("number")
    if event != "pull_request" or action not in _HEAD_MOVED or not (repository and sha and base and number):
        return None
    return repository, sha, Head(number, base, bool(pull.get("draft"))), action


class HeadChecks:
    def __init__(self, reader: Reader) -> None:
        self._reader = reader
        self._required: dict[tuple[str, str], frozenset[str]] = {}
        self._last: dict[tuple[str, int], tuple[str, str]] = {}

    def _required_of(self, repository: str, base: str, *, fresh: bool) -> frozenset[str]:
        if fresh or (repository, base) not in self._required:
            self._required[repository, base] = self._reader.required(repository, base)
        return self._required[repository, base]

    def plan(self, event: str, body: bytes, links: Links) -> Plan:
        """The events `body` (a delivery of `event`) calls for. Raises `OSError` when a GitHub read fails, with nothing planned."""
        report = report_of(event, body)
        if report is not None:
            repository, sha, key = report.repository, report.sha, report.key
            heads, fresh = self._reader.pulls(repository, sha), False
        elif (moved := _moved_head(event, body)) is not None:
            repository, sha, head, key = moved
            heads, fresh = [head], True
        else:
            return Plan([], lambda: None)
        events: list[dict[str, Any]] = []
        rolled: dict[tuple[str, int], tuple[str, str]] = {}
        results: dict[str, str] | None = None
        for head in heads:
            task = links.task_for(repository, head.number)
            if task is None:
                continue
            required = self._required_of(repository, head.base, fresh=fresh)
            if report is not None:
                data = {"repository": repository, "pr": head.number, "sha": sha, "name": report.name, "state": report.state}
                events.append(_event("CHECK_REPORTED", task, (repository, head.number, report.name, key), data | {"required": report.name in required}))
            if head.draft:
                continue
            results = self._reader.results(repository, sha) if results is None else results
            state, unfinished = self._rollup(required, results, report)
            if self._last.get((repository, head.number)) == (sha, state):
                continue
            rolled[repository, head.number] = (sha, state)
            data = {"repository": repository, "pr": head.number, "sha": sha, "state": state, "required": sorted(required), "unfinished": unfinished}
            events.append(_event(f"ROLLUP_{state.upper()}", task, (repository, head.number, sha, state, key), data))
        return Plan(events, lambda: self._last.update(rolled))

    @staticmethod
    def _rollup(required: frozenset[str], results: dict[str, str], report: Report | None) -> tuple[str, list[str]]:
        """The head's state, the delivery standing in for a read that has no final state for its check yet."""
        seen = dict(results)
        if report is not None and seen.get(report.name) not in _FINAL:
            seen[report.name] = report.state
        return rollup(required, seen), sorted(name for name in required if seen.get(name) != "passed")
