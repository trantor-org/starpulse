"""A task's pull requests as moves of the shipped `ci` machine, published to `machine:events`.

GitHub answers what a pull request is now, not what it went through. `parse` keeps the parts of that answer that say
when it was opened, pushed to, force-pushed, checked, conflicted and merged, and `steps` turns them into the machine's
events in order. `CiTrail` publishes each step under an id made of the pull request and the fact (`ci:<url>:push:<sha>`),
so the log's own dedupe makes every poll idempotent, across a restart too, and the log is the only history kept.

GitHub dates a push, a force-push, a check suite and a merge. It dates neither an earlier attempt of a re-run suite nor
a conflict, so a conflict is stamped by the poll that first saw it and an earlier attempt takes the time of the step
before it. A conflict is left only by a new head, because the machine leaves Conflicting by REBASED alone.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from starpulse import events
from starpulse.event_log import EventLog

logger = logging.getLogger(__name__)

MACHINE = "ci"
ACTOR = "github"
#: Conclusions of a finished check suite that fail a push; cancelled, skipped, neutral and stale suites decide nothing.
_FAILED = frozenset({"FAILURE", "TIMED_OUT", "STARTUP_FAILURE"})
_DECIDING = _FAILED | {"SUCCESS"}


@dataclass(frozen=True)
class Suite:
    """One check suite of a head commit; `attempt` is the workflow run's attempt, 1 for an app that has none."""

    done: bool
    conclusion: str | None
    updated: float
    attempt: int


@dataclass(frozen=True)
class Head:
    """A head commit a push (or a force-push, `forced`) put on the branch, at `at`, and the suites it started."""

    oid: str
    at: float
    forced: bool
    suites: tuple[Suite, ...]


@dataclass(frozen=True)
class PullHistory:
    """What GitHub says of one pull request that dates its CI: opened, heads in push order, conflict, merge."""

    url: str
    opened: float
    heads: tuple[Head, ...]
    conflicting: bool
    merged_at: float | None


@dataclass(frozen=True)
class Step:
    """One event of the machine, with the id that makes it the same event on every poll."""

    event_id: str
    event: str
    at: float


def _epoch(text: str) -> float:
    return datetime.fromisoformat(text).timestamp()


def parse(url: str, node: dict) -> PullHistory:
    """The history in one GraphQL `pullRequest` node (the `Pull` fragment of `pull_requests`)."""
    chain = [item["commit"] for item in node.get("commits", {}).get("nodes", [])]
    heads: dict[str, Head] = {}
    for commit in chain:
        suites = tuple(
            Suite(
                done=suite["status"] == "COMPLETED",
                conclusion=suite["conclusion"],
                updated=_epoch(suite["updatedAt"]),
                attempt=(suite.get("workflowRun") or {}).get("runAttempt", 1),
            )
            for suite in commit["checkSuites"]["nodes"]
        )
        if suites:  # a push the checks saw; a commit that started none was not a head
            started = min(_epoch(suite["createdAt"]) for suite in commit["checkSuites"]["nodes"])
            heads[commit["oid"]] = Head(commit["oid"], started, False, suites)
    for push in node.get("timelineItems", {}).get("nodes", []):
        oid, at = push["afterCommit"]["oid"], _epoch(push["createdAt"])
        known = heads.get(oid)
        heads[oid] = Head(oid, at, True, known.suites if known else ())
    return PullHistory(
        url=url,
        opened=_epoch(node["createdAt"]),
        heads=tuple(sorted(heads.values(), key=lambda head: head.at)),
        conflicting=node.get("mergeable") == "CONFLICTING" and not node.get("merged"),
        merged_at=_epoch(node["mergedAt"]) if node.get("mergedAt") else None,
    )


def _checks(head: Head) -> Iterator[tuple[str, str, float | None]]:
    """The head's check events as `(id suffix, event, own time)`; a time of None is unknown, and a step never goes back."""
    suites = [suite for suite in head.suites if suite.conclusion in _DECIDING or not suite.done]
    attempt = max((suite.attempt for suite in head.suites), default=1)
    finished = bool(suites) and all(suite.done for suite in suites)
    for earlier in range(1, attempt):
        yield f"checks:{head.oid}:{earlier}:fail", "CHECKS_FAILED", None
        # a suite still running was updated when its latest attempt started; a finished one does not say when
        latest = earlier + 1 == attempt and not finished
        yield (
            f"rerun:{head.oid}:{earlier + 1}",
            "RERUN",
            max(suite.updated for suite in head.suites) if latest else None,
        )
    if finished:
        failed = any(suite.conclusion in _FAILED for suite in suites)
        yield (
            f"checks:{head.oid}:{attempt}:{'fail' if failed else 'pass'}",
            "CHECKS_FAILED" if failed else "CHECKS_PASSED",
            max(suite.updated for suite in suites),
        )


def steps(pull: PullHistory, *, seen_at: float, floor: float = 0.0) -> list[Step]:
    """The machine events of `pull` in order, none dated before the step ahead of it or before `floor`.

    `seen_at` stamps a conflict, which GitHub does not date.
    """
    out: list[Step] = []

    def add(key: str, event: str, at: float | None) -> None:
        previous = out[-1].at if out else floor
        out.append(Step(f"ci:{pull.url}:{key}", event, previous if at is None else max(at, previous)))

    add("opened", "PR_OPENED", pull.opened)
    for head in pull.heads:
        add(f"{'rebase' if head.forced else 'push'}:{head.oid}", "REBASED" if head.forced else "PUSHED", head.at)
        for key, event, at in _checks(head):
            add(key, event, at)
    if pull.conflicting:
        add(f"conflict:{pull.heads[-1].oid if pull.heads else 'none'}", "CONFLICTED", seen_at)
    if pull.merged_at is not None:
        add("merged", "MERGED", pull.merged_at)
    return out


class CiTrail:
    """Publishes each task's pull request steps to `machine:events`, once each, for `MachineTasks` to draw."""

    def __init__(self, log: EventLog, clock: Callable[[], float] = time.time) -> None:
        self._log = log
        self._clock = clock
        self._published: set[str] = set()
        self._conflicts: dict[str, float] = {}

    def record(self, pulls: Mapping[str, Sequence[PullHistory]]) -> None:
        """Publish the steps of each task's pull requests, oldest pull request first, that were not published before.

        A task's steps stop at the first the log refuses, so the log never holds a task's steps out of order; the
        next poll sends the rest.
        """
        now = self._clock()
        for task, histories in pulls.items():
            floor = 0.0
            for pull in sorted(histories, key=lambda pull: pull.opened):
                if pull.conflicting:
                    seen_at = self._conflicts.setdefault(pull.url, now)
                else:
                    seen_at = self._conflicts.pop(pull.url, now)
                for step in steps(pull, seen_at=seen_at, floor=floor):
                    floor = step.at
                    if step.event_id in self._published:
                        continue
                    if (
                        events.publish(
                            MACHINE,
                            step.event,
                            actor=ACTOR,
                            task=task,
                            now=step.at,
                            event_id=step.event_id,
                            log=self._log,
                        )
                        is None
                    ):
                        logger.warning("ci trail: the log refused %s; %s resumes at the next poll", step.event_id, task)
                        break
                    self._published.add(step.event_id)
                else:
                    continue
                break
