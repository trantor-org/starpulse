"""The PR store as a projection of the lifecycle events our own writers publish on `machine:events`.

Nothing here reads GitHub. A task's events name the task, never the pull request, so each one lands on the pull
requests the Board says the task cites (`BoardFeed.cited`); an event of a task that cites none is dropped. An event
patches the fields it causes on the stored record, or on a new one it opens, and dates the record by its own time
(`fetchedAt`): a record is current until a newer event lands, and an event older than the record is already in it.
Applying an event twice leaves the record as one application did, so the log may be replayed from any point.

A completed job of `ci:jobs` names the pull request it ran for, so it needs no task: it sets the head commit the job
validated and its check's result on a record the store already holds.

A task's events cannot say which of two open pull requests they are about, so one that closes a pull request is
applied only when the task cites a single open one. A record a manual refresh (`POST /api/pulls/refresh`) reads from
GitHub carries what the events cannot: head branch, base, body, merge commit and changed files.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from starpulse._internal.pulls.pull_requests import PULL_URL

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse._internal.eventlog.event_log import Entry
    from starpulse._internal.feed.board_feed import BoardFeed
    from starpulse._internal.pulls.pulls import PullStore

JOBS_STREAM = "ci:jobs"
MACHINE_STREAM = "machine:events"
PULL_MACHINE = "github-pull-request"
TASK_MACHINE = "in-progress"
JOB_RESULTS = {"succeeded": "pass", "failed": "failing"}  # a canceled or unknown job says nothing of its check
CLOSING = {(PULL_MACHINE, "PR_MERGED"), (PULL_MACHINE, "PR_CLOSED")}

Record = dict[str, Any]


def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bare_detail(at: float) -> Record:
    """What the Board reads of a record that no read of GitHub made: nothing known of files or the merge commit."""
    stamp = _iso(at)
    ci = {"createdAt": stamp, "mergeable": "UNKNOWN", "merged": False, "mergedAt": None}
    return {
        "mergedAt": None,
        "mergeSha": None,
        "behindMain": None,
        "files": [],
        "ci": ci | {"commits": {"nodes": []}, "timelineItems": {"nodes": []}},
    }


def _opened(repo: str, number: int, body: str, at: float) -> Record:
    """A record for a pull request the events open: draft, no checks, only what the task says of its body."""
    return {
        "repo": repo,
        "number": number,
        "state": "OPEN",
        "isDraft": True,
        "mergeable": "UNKNOWN",
        "baseRefName": "main",
        "headRefOid": "",
        "body": body,
        "checks": "none",
        "requiredChecks": [],
        "threads": 0,
        "updatedAt": _iso(at),
        "mergedAt": None,
        "mergeSha": None,
        "fetchedAt": at,
        "headRefName": "",
        "unresolvedThreads": None,
        "detail": _bare_detail(at),
    }


def _closed(state: str) -> Callable[[Record, Mapping[str, Any], float], Record]:
    def delta(record: Record, _fields: Mapping[str, Any], at: float) -> Record:
        stamp = _iso(at) if state == "MERGED" else None
        detail = record["detail"] or _bare_detail(at)
        ci = detail["ci"] | {"merged": state == "MERGED", "mergedAt": stamp}
        return {"state": state, "mergedAt": stamp, "detail": detail | {"mergedAt": stamp, "ci": ci}}

    return delta


def _threads(_record: Record, fields: Mapping[str, Any], _at: float) -> Record:
    count = int(fields["unresolved"])
    return {"threads": count} | ({"unresolvedThreads": []} if count == 0 else {})


#: What each event causes in the record, by (machine, event); a push leaves the head to the next `ci:jobs` entry.
_DELTAS: dict[tuple[str, str], Callable[[Record, Mapping[str, Any], float], Record]] = {
    (PULL_MACHINE, "PR_OPENED"): lambda *_: {"state": "OPEN"},
    (TASK_MACHINE, "PR_READY"): lambda *_: {"isDraft": False},
    (TASK_MACHINE, "PUSHED"): lambda *_: {"checks": "pending", "requiredChecks": [], "mergeable": "UNKNOWN"},
    (PULL_MACHINE, "CHECKS_PASSED"): lambda *_: {"checks": "pass"},
    (PULL_MACHINE, "CHECKS_FAILED"): lambda *_: {"checks": "failing"},
    (PULL_MACHINE, "CONFLICTED"): lambda *_: {"mergeable": "CONFLICTING"},
    (PULL_MACHINE, "MERGEABLE"): lambda *_: {"mergeable": "MERGEABLE"},
    (PULL_MACHINE, "THREADS_CHANGED"): _threads,
    (PULL_MACHINE, "PR_MERGED"): _closed("MERGED"),
    (PULL_MACHINE, "PR_CLOSED"): _closed("CLOSED"),
}


class PullProjection:
    """Keeps `store`'s records current from the machine events handed to `handle`, calling `changed` after each
    event that changed one."""

    def __init__(self, store: PullStore, feed: BoardFeed, changed: Callable[[], None] | None = None) -> None:
        self._store = store
        self._feed = feed
        self._changed = changed

    def _cited(self, key: str) -> list[tuple[str, int]]:
        """The pull requests the task cites, as (repository, number)."""
        matches = (PULL_URL.fullmatch(url) for url in self._feed.cited(key))
        return [(match[1], int(match[2])) for match in matches if match]

    def _body(self, key: str) -> str:
        """The body a record opened by events carries: the task and the session holding it, so the lookups readers make
        by either find it."""
        holder = (self._feed.task(key) or {}).get("holder") or ""
        return f"{key} {holder}".strip()

    def handle(self, entry: Entry) -> None:
        """Apply one `machine:events` entry; one that is no event of a task's pull request, or whose time is unreadable,
        is dropped."""
        fields = entry.fields
        name = (fields.get("machine"), fields.get("event"))
        key = fields.get("task")
        if name not in _DELTAS or not key:
            return
        try:
            at = float(fields["time"])
        except KeyError, TypeError, ValueError:
            return
        saved = []
        for repo, number in self._targets(key, name in CLOSING):
            found = self._store.find(repo=repo, number=number, detailed=True)
            record = found[0] if found else _opened(repo, number, self._body(key), at)
            if found and at < record["fetchedAt"]:
                continue  # the record already holds what a later event or read says
            patched = record | _DELTAS[name](record, fields, at) | {"fetchedAt": at, "updatedAt": _iso(at)}
            if not found or patched != record:
                saved.append(patched)
        if saved:
            self._store.save(saved)
            if self._changed:
                self._changed()

    def _targets(self, key: str, closing: bool) -> list[tuple[str, int]]:
        """The task's pull requests an event applies to: those still open, and for a close only a lone one."""
        pulls = self._cited(key)
        stored = {pull: self._store.find(repo=pull[0], number=pull[1]) for pull in pulls}
        opened = [pull for pull in pulls if not stored[pull] or stored[pull][0]["state"] == "OPEN"]
        return opened if not closing or len(opened) == 1 else []

    def handle_job(self, entry: Entry) -> None:
        """Apply one `ci:jobs` entry to the record of the pull request it ran for; one for a pull request the store does
        not hold, with no result to record, or with unreadable fields is dropped. A job of another head than the
        record's replaces the head and its checks only if it is no older than the record: a replayed job of an earlier
        head must not take them back."""
        fields = entry.fields
        result = JOB_RESULTS.get(str(fields.get("result")))
        try:
            repo, number, at = str(fields["repository"]), int(fields["pr"]), float(fields["time"])
            head, job = str(fields["head_sha"]), str(fields["job"])
        except KeyError, TypeError, ValueError:
            return
        found = self._store.find(repo=repo, number=number, detailed=True)
        if not result or not found:
            return
        record = found[0]
        if head != record["headRefOid"]:
            if at < record["fetchedAt"]:
                return
            checks = []
        else:
            checks = [check for check in record["requiredChecks"] if check["name"] != job]
        checks = sorted([*checks, {"name": job, "result": result}], key=lambda check: check["name"])
        patched = record | {"headRefOid": head, "requiredChecks": checks, "fetchedAt": max(at, record["fetchedAt"])}
        if patched != record:
            self._store.save([patched])
            if self._changed:
                self._changed()
