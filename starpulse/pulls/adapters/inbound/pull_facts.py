"""What the saved deliveries other than `pull_request` say of a pull request's record: required-check results, review
threads, the CI trail and force pushes.

A delivery that names a head SHA (`check_run`, `status`, `check_suite`, `workflow_run`) writes each open record whose
head it is. A required check is one the record already names; a result for any other check is not the record's. A
delivery whose pull request the store lacks writes nothing: the reconcile brings that record in whole.
"""

from collections.abc import Callable, Mapping
from typing import Any

from starpulse.contracts.stamps import iso_utc
from starpulse.github.model.delivery import Delivery
from starpulse.pulls.adapters.outbound.pull_events import Record, bare_detail
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.pulls.model.required import rollup_state

__all__ = ["FACTS", "Handler", "forced_push"]

Handler = Callable[[PullStore, Delivery, Mapping[str, Any], float], bool]
Edit = Callable[[Record, float], Record]

_PASSED = frozenset({"success", "neutral", "skipped"})
_STATUS_RESULTS = {"success": "pass", "pending": "pending"}  # any other state fails


def _write(store: PullStore, records: list[Record], edit: Edit, now: float, head: str | None = None) -> bool:
    def change(current: Record | None) -> Record | None:
        if not current or (head is not None and current["headRefOid"] != head):  # a push moved the head since the read
            return None
        delta = edit(current, now)
        return current | delta if delta else None

    return any([store.amend(record["repo"], record["number"], change) for record in records])


def _at_head(store: PullStore, repo: str, sha: str) -> list[Record]:
    return [record for record in store.find(repo, state="OPEN") if sha and record["headRefOid"] == sha]


def _posted(name: str, result: str) -> Edit:
    def edit(record: Record, now: float) -> Record:
        checks = record["requiredChecks"]
        if name not in {check["name"] for check in checks}:
            return {}
        posted = [{**check, "result": result} if check["name"] == name else check for check in checks]
        rollup = {"sha": record["headRefOid"], "state": rollup_state(posted), "at": now}  # the rollup the posted results make, as GitHub's
        return {"requiredChecks": posted, "rollup": rollup, "fetchedAt": max(now, record["fetchedAt"])}  # `PullStore._guarded` reads these

    return edit


def _check_run(store: PullStore, delivery: Delivery, payload: Mapping[str, Any], now: float) -> bool:
    if delivery.action != "completed":
        return False
    run = payload["check_run"]
    result = "pass" if run["conclusion"] in _PASSED else "failing"
    return _write(store, _at_head(store, delivery.repository, run["head_sha"]), _posted(run["name"], result), now, run["head_sha"])


def _status(store: PullStore, delivery: Delivery, payload: Mapping[str, Any], now: float) -> bool:
    result = _STATUS_RESULTS.get(payload["state"], "failing")
    return _write(store, _at_head(store, delivery.repository, payload["sha"]), _posted(payload["context"], result), now, payload["sha"])


def _with_suite(ci: Mapping[str, Any], sha: str, suite_id: int, fields: Record) -> Record:
    """`ci` with suite `suite_id` of commit `sha` changed by `fields`, made first when unknown; the commit joins the
    chain at its end when the trail lacks it."""
    commits = list(ci["commits"]["nodes"])
    at = next((i for i, node in enumerate(commits) if node["commit"]["oid"] == sha), len(commits))
    commit = commits[at]["commit"] if at < len(commits) else {"oid": sha, "checkSuites": {"nodes": []}}
    suites = commit["checkSuites"]["nodes"]
    known = next((suite for suite in suites if suite.get("id") == suite_id), {})
    suite = {"id": suite_id} | known | fields
    node = {"commit": commit | {"checkSuites": {"nodes": [s for s in suites if s is not known] + [suite]}}}
    return dict(ci) | {"commits": {"nodes": [*commits[:at], node, *commits[at + 1 :]]}}


def _suite(sha: str, suite_id: int, fields: Record) -> Edit:
    def edit(record: Record, now: float) -> Record:
        detail = record["detail"] or bare_detail(now)
        return {"detail": detail | {"ci": _with_suite(detail["ci"], sha, suite_id, fields)}}

    return edit


def _upper(value: str | None) -> str | None:
    return value.upper() if value else None


def _stamped(run: Mapping[str, Any]) -> Record:
    return {
        "status": _upper(run["status"]),
        "conclusion": _upper(run["conclusion"]),
        "createdAt": run["created_at"],
        "updatedAt": run["updated_at"],
    }


def _check_suite(store: PullStore, delivery: Delivery, payload: Mapping[str, Any], now: float) -> bool:
    if delivery.action != "completed":
        return False
    suite = payload["check_suite"]
    if "head_sha" not in suite:  # a reconcile row queued before its body carried the head
        return False
    edit = _suite(suite["head_sha"], suite["id"], _stamped(suite))
    return _write(store, _at_head(store, delivery.repository, suite["head_sha"]), edit, now, suite["head_sha"])


def _workflow_run(store: PullStore, delivery: Delivery, payload: Mapping[str, Any], now: float) -> bool:
    run = payload["workflow_run"]
    edit = _suite(run["head_sha"], run["check_suite_id"], _stamped(run) | {"workflowRun": {"runAttempt": run["run_attempt"]}})
    return _write(store, _at_head(store, delivery.repository, run["head_sha"]), edit, now, run["head_sha"])


def _forced(sha: str, at: float) -> Edit:
    def edit(record: Record, now: float) -> Record:
        detail = record["detail"] or bare_detail(now)
        items = detail["ci"]["timelineItems"]["nodes"]
        if any(item["afterCommit"]["oid"] == sha for item in items):
            return {}
        item = {"createdAt": iso_utc(at), "afterCommit": {"oid": sha}}
        return {"detail": detail | {"ci": detail["ci"] | {"timelineItems": {"nodes": [*items, item]}}}}

    return edit


def forced_push(store: PullStore, delivery: Delivery, payload: Mapping[str, Any], now: float) -> bool:
    """Add a force push of a pull request's head branch to its CI trail; the other pushes are the reads'."""
    if not payload.get("forced"):
        return False
    branch = str(payload["ref"]).removeprefix("refs/heads/")
    pushed = payload["repository"].get("pushed_at")
    at = float(pushed) if isinstance(pushed, int | float) else now
    headed = [pull for pull in store.find(delivery.repository, state="OPEN") if pull["headRefName"] == branch]
    return _write(store, headed, _forced(payload["after"], at), now)


def _thread_edit(change: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]) -> Edit:
    def edit(record: Record, _now: float) -> Record:
        held = record["unresolvedThreads"] or []
        threads = change(list(held))
        same = [thread["id"] for thread in threads] == [thread["id"] for thread in held]
        return {} if same else {"threads": len(threads), "unresolvedThreads": threads}

    return edit


def _opens(comment: Mapping[str, Any]) -> Edit:
    thread = {"id": str(comment["id"]), "author": (comment.get("user") or {}).get("login")}  # keyed by its first comment
    return _thread_edit(lambda threads: threads if any(t["id"] == thread["id"] for t in threads) else [*threads, thread])


def _resolves(comment: Mapping[str, Any]) -> Edit:
    return _thread_edit(lambda threads: [thread for thread in threads if thread["id"] != str(comment["id"])])


def _in_pull(store: PullStore, delivery: Delivery, payload: Mapping[str, Any]) -> list[Record]:
    return store.find(delivery.repository, payload["pull_request"]["number"])


def _review_comment(store: PullStore, delivery: Delivery, payload: Mapping[str, Any], now: float) -> bool:
    comment = payload["comment"]
    if delivery.action != "created" or comment.get("in_reply_to_id"):  # a reply joins a thread an earlier comment opened
        return False
    return _write(store, _in_pull(store, delivery, payload), _opens(comment), now)


def _review_thread(store: PullStore, delivery: Delivery, payload: Mapping[str, Any], now: float) -> bool:
    first = payload["thread"]["comments"][0]
    edits = {"resolved": _resolves(first), "unresolved": _opens(first)}
    return delivery.action in edits and _write(store, _in_pull(store, delivery, payload), edits[delivery.action], now)


FACTS: dict[str, Handler] = {
    "check_run": _check_run,
    "status": _status,
    "check_suite": _check_suite,
    "workflow_run": _workflow_run,
    "pull_request_review_comment": _review_comment,
    "pull_request_review_thread": _review_thread,
}
