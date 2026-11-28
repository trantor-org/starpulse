"""The PR store as a projection of the lifecycle events our own writers publish on `machine:events`.

Nothing here reads GitHub. A task's events name the task, never the pull request, so each one lands on the pull
requests the Board says the task cites (`BoardFeed.cited`); an event of a task that cites none is dropped, except a close
that names its pull request, which applies to that one (a worker's feed may not yet hold the citation). An event
patches the fields it causes on the stored record, or on a new one it opens, and dates the record by its own time
(`fetchedAt`): a record is current until a newer event lands, and an event older than the record is already in it.
Applying an event twice leaves the record as one application did, so the log may be replayed from any point.

A completed job of `ci:jobs` names the pull request it ran for, so it needs no task: it sets the head commit the job
validated and its check's result on a record the store already holds. The same job also arrives as an event of the
`ci-job` machine on `machine:events`, its pull request, head commit and job in `data`; both are read until the
`ci:jobs` stream is dropped.

A task's events cannot say which of two open pull requests they are about, so one that closes a pull request is
applied only when the task cites a single open one, unless its `repository` and `pr` fields name the pull request it
closed: it then applies to that one alone, and to none once the store holds it closed. A head's rollup
(`ROLLUP_*` of the `pr-checks` machine) is applied the same way, to the pull request it names, and stored as `{sha, state}`
whatever the record's age: the board reads a pull request as checks passed only when the rollup of its current head
says so. A reopen
(`PR_REOPENED`) is the reverse: it applies to a closed record, never a merged one, by the same naming. A record a webhook delivery
(`starpulse.pulls.adapters.inbound.pull_deliveries`) writes carries what the events cannot: head branch, base, body,
merge commit and changed files.
"""

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from starpulse.contracts.stamps import iso_utc
from starpulse.pulls.adapters.outbound.pull_requests import PULL_URL

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.board.model.board_feed import BoardFeed
    from starpulse.event_log.event_log import Entry
    from starpulse.pulls.adapters.outbound.pulls import PullStore

JOBS_STREAM = "ci:jobs"
MACHINE_STREAM = "machine:events"
GITHUB_MACHINE = "github-pull-request"
JOB_MACHINE = "ci-job"
CHECKS_MACHINE = "pr-checks"
TASK_MACHINES = ("deliver", "in-progress")  # `in-progress` keeps replayed history that predates the deliver machine
JOB_RESULTS = {"succeeded": "pass", "failed": "failing"}  # a canceled or unknown job says nothing of its check
JOB_EVENTS = {"JOB_SUCCEEDED": "succeeded", "JOB_FAILED": "failed"}  # a `ci-job` event as the result `ci:jobs` names
CLOSING = {(GITHUB_MACHINE, "PR_MERGED"), (GITHUB_MACHINE, "PR_CLOSED")}
REOPENING = (GITHUB_MACHINE, "PR_REOPENED")
MERGING = (GITHUB_MACHINE, "PR_MERGED")
ROLLUPS = {(CHECKS_MACHINE, f"ROLLUP_{state}") for state in ("PASSED", "FAILING", "PENDING")}
REPORTED = (CHECKS_MACHINE, "CHECK_REPORTED")
REPORT_RESULTS = {"passed": "pass", "failing": "failing", "pending": "pending"}

Record = dict[str, Any]


def unjudged(record: Record) -> Record:
    """What a new head does to the stored mergeability: a verdict of the head the record names (a conflict before a
    rebase push) says nothing of the new one. A record with no head (a `PUSHED` cleared it) keeps its verdict: the
    pre-push hook judged the new head after that push."""
    return {"mergeable": "UNKNOWN"} if record["headRefOid"] else {}


def bare_detail(at: float) -> Record:
    """What the Board reads of a record that no read of GitHub made: nothing known of files or the merge commit."""
    stamp = iso_utc(at)
    ci = {"createdAt": stamp, "mergeable": "UNKNOWN", "merged": False, "mergedAt": None}
    return {
        "mergedAt": None,
        "mergeSha": None,
        "behindMain": None,
        "files": None,
        "ci": ci | {"commits": {"nodes": []}, "timelineItems": {"nodes": []}},
    }


def opened(repo: str, number: int, body: str, at: float) -> Record:
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
        "rollup": None,
        "requiredChecks": [],
        "threads": 0,
        "updatedAt": iso_utc(at),
        "mergedAt": None,
        "mergeSha": None,
        "fetchedAt": at,
        "headRefName": "",
        "unresolvedThreads": None,
        "title": "",
        "detail": bare_detail(at),
    }


def _closed(state: str) -> Callable[[Record, Mapping[str, Any], float], Record]:
    def delta(record: Record, _fields: Mapping[str, Any], at: float) -> Record:
        stamp = iso_utc(at) if state == "MERGED" else None
        detail = record["detail"] or bare_detail(at)
        closed = {"closed": state == "CLOSED", "closedAt": None if stamp else iso_utc(at)}
        ci = detail["ci"] | {"merged": state == "MERGED", "mergedAt": stamp} | closed
        return {"state": state, "mergedAt": stamp, "detail": detail | {"mergedAt": stamp, "ci": ci}}

    return delta


def reopened(record: Record, _fields: Mapping[str, Any], at: float) -> Record:
    """An open record again, its CI detail no longer closed."""
    detail = record["detail"] or bare_detail(at)
    return {"state": "OPEN", "detail": detail | {"ci": detail["ci"] | {"closed": False, "closedAt": None}}}


def _threads(_record: Record, fields: Mapping[str, Any], _at: float) -> Record:
    count = int(fields["unresolved"])
    return {"threads": count} | ({"unresolvedThreads": []} if count == 0 else {})


def _rollup(record: Record, fields: Mapping[str, Any], at: float) -> Record:
    data = fields["data"]
    return {
        "rollup": {"sha": str(data["sha"]), "state": str(data["state"]), "at": at}
    }  # the store derives `checks` from it


def _reported(record: Record, fields: Mapping[str, Any], _at: float) -> Record:
    data = fields["data"]
    if not (
        data.get("required")
        and data.get("sha") == record["headRefOid"]
        and (data.get("repository"), data.get("pr")) == (record["repo"], record["number"])
    ):
        return {}
    result = REPORT_RESULTS.get(str(data.get("state")))
    checks = [check for check in record["requiredChecks"] if check["name"] != data["name"]]
    return (
        {
            "requiredChecks": sorted(
                [*checks, {"name": str(data["name"]), "result": result}], key=lambda check: check["name"]
            )
        }
        if result
        else {}
    )


def _mergeability(value: str) -> Callable[[Record, Mapping[str, Any], float], Record]:
    def delta(record: Record, fields: Mapping[str, Any], _at: float) -> Record:
        data = fields.get("data")
        sha = data.get("sha") if isinstance(data, Mapping) else None
        # a result of another head than the record's (a sibling task's push) says nothing of this head
        return {} if sha and record["headRefOid"] and sha != record["headRefOid"] else {"mergeable": value}

    return delta


#: What each event causes in the record, by (machine, event); a push leaves the head to the next `ci:jobs` entry.
_DELTAS: dict[tuple[str, str], Callable[[Record, Mapping[str, Any], float], Record]] = {
    (GITHUB_MACHINE, "PR_OPENED"): lambda *_: {"state": "OPEN"},
    REOPENING: reopened,
    (GITHUB_MACHINE, "CONFLICTED"): _mergeability("CONFLICTING"),
    (GITHUB_MACHINE, "MERGEABLE"): _mergeability("MERGEABLE"),
    (GITHUB_MACHINE, "THREADS_CHANGED"): _threads,
    (GITHUB_MACHINE, "PR_MERGED"): _closed("MERGED"),
    (GITHUB_MACHINE, "PR_CLOSED"): _closed("CLOSED"),
}

_TASK_DELTAS = {
    "PR_READY": lambda *_: {"isDraft": False},
    # no head: `checks` pending until the delivery names the new one; the rollup forgets the replaced head's verdict, so a
    # read of that head begun before the push and saved after it never reads green again
    "PUSHED": lambda _record, _fields, at: {
        "headRefOid": "",
        "requiredChecks": [],
        "mergeable": "UNKNOWN",
        "rollup": {"sha": "", "state": "pending", "at": at},
    },
}
_DELTAS |= dict.fromkeys(ROLLUPS, _rollup)
_DELTAS[REPORTED] = _reported
for _machine in TASK_MACHINES:
    _DELTAS |= {(_machine, event): delta for event, delta in _TASK_DELTAS.items()}


class RecordProjection:
    """Keeps `store`'s records current from the machine events handed to `handle`, calling `changed` after each
    event that changed one."""

    def __init__(
        self,
        store: PullStore,
        feed: BoardFeed,
        changed: Callable[[], None] | None = None,
    ) -> None:
        self._store = store
        self._feed = feed
        self._changed = changed
        self._readied: dict[str, tuple[tuple[str, str], str, Mapping[str, Any], float]] = {}

    def _cited(self, key: str) -> list[tuple[str, int]]:
        """The pull requests the task cites, as (repository, number)."""
        matches = (PULL_URL.fullmatch(url) for url in self._feed.cited(key))
        return [(match[1], int(match[2])) for match in matches if match]

    def _body(self, key: str) -> str:
        """The body a record opened by events carries: the task and the session holding it, so the lookups readers make
        by either find it."""
        assignee = (self._feed.task(key, lean=True) or {}).get("assignee") or ""
        return f"{key} {assignee}".strip()

    def handle(self, entry: Entry) -> None:
        """Apply one `machine:events` entry; one that is no event of a task's pull request, or whose time is unreadable,
        is dropped. A `PR_READY` that found no cited pull request is applied once the task cites one, as an event of the
        task finds it does."""
        fields = entry.fields
        if fields.get("machine") == JOB_MACHINE:
            self._job_event(fields)
            return
        name = (fields.get("machine"), fields.get("event"))
        key = fields.get("task")
        if key in self._readied and self._cited(key):
            self._project(*self._readied.pop(key))
        if name not in _DELTAS or not key or (name in ROLLUPS | {REPORTED} and not self._rolled(fields)):
            return
        try:
            at = float(fields["time"])
        except KeyError, TypeError, ValueError:
            return
        if not self._project(name, key, fields, at) and name[1] == "PR_READY":
            self._readied[key] = (name, key, fields, at)

    def _project(self, name: tuple[str, str], key: str, fields: Mapping[str, Any], at: float) -> bool:
        """Write `name`'s delta to the task's pull requests it applies to, and say whether it applied to any."""
        targets = self._targets(key, name, fields)
        saved = [self._amend(repo, number, name, key, fields, at) for repo, number in targets]
        if any(saved) and self._changed:
            self._changed()
        return bool(targets)

    def _amend(
        self, repo: str, number: int, name: tuple[str, str], key: str, fields: Mapping[str, Any], at: float
    ) -> bool:
        # read under the store's lock, so a delivery naming the head between a read and the save is never written over

        def change(found: Record | None) -> Record | None:
            if found and at < found["fetchedAt"] and name != MERGING and name not in ROLLUPS:
                return None  # the record already holds what a later event or delivery says; a merge or a rollup, which names its head, is never older than that
            if name in ROLLUPS and found and at < ((found.get("rollup") or {}).get("at") or 0):
                return None  # an older rollup, of a head the pull request has since left, must not replace the newer verdict
            record = found or opened(repo, number, self._body(key), at)
            stamps = {"fetchedAt": max(at, record["fetchedAt"]), "updatedAt": iso_utc(at)}  # a late event never ages it
            patched = record | _DELTAS[name](record, fields, at) | stamps
            return patched if not found or patched != record else None

        return self._store.amend(repo, number, change)

    @staticmethod
    def _rolled(fields: Mapping[str, Any]) -> bool:
        """Whether a rollup event carries the head and state it stores."""
        data = fields.get("data")
        return isinstance(data, Mapping) and bool(data.get("sha")) and bool(data.get("state"))

    def _targets(self, key: str, name: tuple[str, str], fields: Mapping[str, Any]) -> list[tuple[str, int]]:
        """The task's pull requests an event applies to: those still open, for a reopen those closed unmerged, and for a
        close or a reopen the one it names (`pr`, or the intake's `pull_request`), at the top level or under `data`;
        one naming none applies only to a lone candidate."""
        named = self._named(fields)
        # a task citing none (its feed not yet warm, or the citation not yet written) leaves a close naming its pull
        # request the only evidence; the pull request merged whoever cites it
        pulls = self._cited(key) or ([named] if named and name in CLOSING else [])
        stored = {pull: self._store.find(repo=pull[0], number=pull[1]) for pull in pulls}
        wanted = "CLOSED" if name == REOPENING else "OPEN"
        candidates = [pull for pull in pulls if not stored[pull] or stored[pull][0]["state"] == wanted]
        if name[1] == "PUSHED" and isinstance(data := fields.get("data"), Mapping) and data.get("repository"):
            pushed = str(data["repository"]).lower()  # GitHub names ignore case
            return [
                pull for pull in candidates if pull[0].lower() == pushed
            ]  # a push to one repository leaves another's head standing
        if name not in CLOSING | ROLLUPS | {REOPENING}:
            return candidates
        if named:
            return [named] if named in candidates else []
        return candidates if len(candidates) == 1 else []

    @staticmethod
    def _named(fields: Mapping[str, Any]) -> tuple[str, int] | None:
        """The pull request an event names (`pr`, or the intake's `pull_request`), at the top level or under `data`, as
        (repository, number)."""
        data = fields.get("data")
        naming = data if isinstance(data, Mapping) and ("pr" in data or "pull_request" in data) else fields
        number = str(naming.get("pr", naming.get("pull_request", "")))
        return (str(naming.get("repository")), int(number)) if number.isdigit() else None

    def handle_job(self, entry: Entry) -> None:
        """Apply one `ci:jobs` entry to the record of the pull request it ran for; one for a pull request the store does
        not hold, with no result to record, or with unreadable fields is dropped. A job of another head than the
        record's replaces the head and its checks only if it is no older than the record: a replayed job of an earlier
        head must not take them back."""
        self._apply_job(entry.fields)

    def _job_event(self, fields: Mapping[str, Any]) -> None:
        """Apply a `ci-job` machine event as the `ci:jobs` entry it stands for; one without data is dropped."""
        data = fields.get("data")
        result = JOB_EVENTS.get(str(fields.get("event")))
        if isinstance(data, Mapping) and result:
            self._apply_job({**data, "result": result, "time": fields.get("time")})

    def _apply_job(self, fields: Mapping[str, Any]) -> None:
        result = JOB_RESULTS.get(str(fields.get("result")))
        try:
            repo, number, at = str(fields["repository"]), int(fields["pr"]), float(fields["time"])
            head, job = str(fields["head_sha"]), str(fields["job"])
        except KeyError, TypeError, ValueError:
            return
        if not result:
            return

        def change(record: Record | None) -> Record | None:
            if not record:
                return None
            if head != record["headRefOid"]:
                if at < record["fetchedAt"]:
                    return None
                checks, moved = [], unjudged(record)
            else:
                checks, moved = [check for check in record["requiredChecks"] if check["name"] != job], {}
            checks = sorted([*checks, {"name": job, "result": result}], key=lambda check: check["name"])
            stamps = {"headRefOid": head, "requiredChecks": checks, "fetchedAt": max(at, record["fetchedAt"])}
            patched = record | moved | stamps
            return patched if patched != record else None

        if self._store.amend(repo, number, change) and self._changed:
            self._changed()
