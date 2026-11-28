"""A check or pull request delivery as the `pr-checks` events of its head: each check's report and the head's rollup.

`HeadChecks.plan` reads what a delivery alone cannot say (the open pull requests of its commit, the base branch's
required checks, every check posted on the head) and returns the events to publish. The required set is cached per
base branch and read again on each `pull_request` delivery, so a ruleset is never polled. A head's pull requests and posted
checks are read once, then kept current by the deliveries, and a delivery whose payload names only unlinked pull requests
reads nothing. While GitHub's quota is spent no read is made. A head's rollup is published
only when its state changes or a required check fails again with a report not seen before, and only for a pull request that is not a draft
and a commit that is still the head its last `pull_request` delivery or pull request read named: a late check of a replaced commit would swap the rollup back and forth with the new head's.
A check that posts pending after a final result on a head whose rollup is failing is a rerun of that head: its failures read pending until they report again.
"""

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from starpulse.github.adapters.outbound.rest import RateLimited
from starpulse.github.model.checks import Report, dict_of, report_of, rollup
from starpulse.github.model.events import SOURCE
from starpulse.github.ports.events import Head, Links, Reader

__all__ = ["HeadChecks", "Plan"]

MACHINE = "pr-checks"
#: The `pull_request` actions that move a head or make it ready, and so call for a fresh rollup.
_HEAD_MOVED = frozenset({"opened", "reopened", "synchronize", "ready_for_review", "converted_to_draft"})
_FINAL = frozenset({"passed", "failing"})
#: The most heads whose pull requests and results are kept.
_KEPT = 512


@dataclass(frozen=True)
class Plan:
    """The `events` to post for a delivery; `settle` records that the rollups among them were posted."""

    events: list[dict[str, Any]]
    settle: Callable[[], None]


def _put(cache: dict[Any, Any], key: Any, value: Any) -> None:
    """Remember `value`, forgetting the oldest entry past `_KEPT`."""
    cache[key] = value
    while len(cache) > _KEPT:
        del cache[next(iter(cache))]


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
    def __init__(self, reader: Reader, clock: Callable[[], float] = time.time) -> None:
        self._reader, self._clock = reader, clock
        self._limited_until = 0.0
        self._heads: dict[tuple[str, str], list[Head]] = {}
        self._results: dict[tuple[str, str], dict[str, str]] = {}
        self._stamps: dict[tuple[str, str], dict[str, str]] = {}
        self._required: dict[tuple[str, str], frozenset[str]] = {}
        self._last: dict[tuple[str, int], tuple[str, str, str]] = {}
        self._pushed: dict[tuple[str, int], str] = {}

    def _required_of(self, repository: str, base: str, *, fresh: bool) -> frozenset[str]:
        if fresh or (repository, base) not in self._required:
            self._required[repository, base] = self._reader.required(repository, base)
        return self._required[repository, base]

    def plan(self, event: str, body: bytes, links: Links) -> Plan:
        """The events `body` (a delivery of `event`) calls for. Raises `OSError` when a GitHub read fails, with nothing planned,
        and `RateLimited` without a read while the quota is spent."""
        if self._clock() < self._limited_until:
            raise RateLimited(403, "(quota spent)", self._limited_until)
        try:
            return self._plan(event, body, links)
        except RateLimited as exc:
            self._limited_until = exc.until
            raise

    def _forget(self, event: str, body: bytes) -> None:
        """Drop what is kept of the head a `pull_request` delivery is about: it may be closed, drafted or readied."""
        if event != "pull_request":
            return
        try:
            payload = dict_of(json.loads(body))
        except ValueError:
            return
        key = dict_of(payload.get("repository")).get("full_name"), dict_of(dict_of(payload.get("pull_request")).get("head")).get("sha")
        self._heads.pop(key, None)
        self._results.pop(key, None)
        self._stamps.pop(key, None)

    def _heads_of(self, repository: str, sha: str, report: Report, links: Links) -> list[Head]:
        """The open pull requests of the head, read once per commit; none when the payload names only unlinked ones.
        The read names only pull requests whose head is `sha`, so it marks `sha` pushed before their `pull_request` delivery does."""
        if report.pulls and not any(links.task_for(repository, number) for number in report.pulls):
            return []
        if (repository, sha) not in self._heads:
            _put(self._heads, (repository, sha), self._reader.pulls(repository, sha))
            for head in self._heads[repository, sha]:
                _put(self._pushed, (repository, head.number), sha)
        return self._heads[repository, sha]

    def _stale(self, repository: str, sha: str, report: Report) -> bool:
        """Whether `report` is older than what is kept for its check: a replay after a stall, already overtaken."""
        kept = self._stamps.get((repository, sha), {}).get(report.name)
        if not (kept and report.at):
            return False
        held = self._results.get((repository, sha), {}).get(report.name)
        return report.at < kept or (report.at == kept and held in _FINAL and report.state not in _FINAL)

    def _results_of(self, repository: str, sha: str, report: Report | None) -> dict[str, str]:
        """What was posted on the head: read once, then kept current by each delivery, which `_plan` has checked is no older than what is kept."""
        key = repository, sha
        if key not in self._results:
            seen = self._reader.results(repository, sha)
            if report is not None and seen.get(report.name) not in _FINAL:
                seen[report.name] = report.state
            _put(self._results, key, seen)
            _put(self._stamps, key, dict.fromkeys(seen, report.at) if report is not None else {})
        elif report is not None:
            self._results[key][report.name] = report.state
            self._stamps[key][report.name] = report.at or self._stamps[key].get(report.name, "")
        return self._results[key]

    def _plan(self, event: str, body: bytes, links: Links) -> Plan:
        report = report_of(event, body)
        if report is not None and self._stale(report.repository, report.sha, report):
            return Plan([], lambda: None)
        if report is not None:
            repository, sha, key = report.repository, report.sha, report.key
            heads, fresh = self._heads_of(repository, sha, report, links), False
        elif (moved := _moved_head(event, body)) is not None:
            repository, sha, head, key = moved
            heads, fresh = [head], True
            _put(self._pushed, (repository, head.number), sha)
        else:
            self._forget(event, body)
            return Plan([], lambda: None)
        if report is None:
            self._forget(event, body)
        rerun = report is not None and report.state == "pending" and self._results.get((report.repository, report.sha), {}).get(report.name) in _FINAL
        events: list[dict[str, Any]] = []
        rolled: dict[tuple[str, int], tuple[str, str, str]] = {}
        for head in heads:
            task = links.task_for(repository, head.number)
            if task is None:
                continue
            required = self._required_of(repository, head.base, fresh=fresh)
            if report is not None:
                data = {"repository": repository, "pr": head.number, "sha": sha, "name": report.name, "state": report.state}
                events.append(_event("CHECK_REPORTED", task, (repository, head.number, report.name, key), data | {"required": report.name in required}))
            if head.draft or self._pushed.get((repository, head.number), sha) != sha:  # a late check of a commit a push replaced
                continue
            results = self._results_of(repository, sha, report)
            last = self._last.get((repository, head.number))
            if rerun and last is not None and last[:2] == (sha, "failing"):  # a check posted again: the head's run restarted, so its failures are being redone
                results.update({name: "pending" for name, seen in results.items() if seen == "failing"})
            state, unfinished = self._rollup(required, results)
            refailed = state == "failing" and report is not None and report.state == "failing" and report.name in required
            mark = (sha, state, key if refailed else "")
            if last == mark or (last is not None and last[:2] == mark[:2] and not refailed):
                continue
            rolled[repository, head.number] = mark
            data = {"repository": repository, "pr": head.number, "sha": sha, "state": state, "required": sorted(required), "unfinished": unfinished}
            if refailed and report is not None:
                data |= {"check": report.name, "at": report.at or None}  # the wake line reads alike without them
            events.append(_event(f"ROLLUP_{state.upper()}", task, (repository, head.number, sha, state, key), data))
        return Plan(events, lambda: self._last.update(rolled))

    @staticmethod
    def _rollup(required: frozenset[str], seen: dict[str, str]) -> tuple[str, list[str]]:
        return rollup(required, seen), sorted(name for name in required if seen.get(name) != "passed")
