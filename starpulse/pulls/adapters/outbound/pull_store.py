"""The single-pull-request read behind `POST /api/pulls/refresh`, and the thread that serves it.

The PR store is a projection of lifecycle events (`starpulse.pulls.adapters.outbound.pull_events`); nothing here polls GitHub.
`refresh_pull` reads one pull request alone (its facts, required checks at the head commit and review threads, one
`query_github`) and replaces its record, for the manual read of `pr_status --live` and for a pull request a close
event relays (`PullSync.request`). `isRequired` takes the PR's number, so a required check can only be read through
`pullRequest(number:)`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from typing import TYPE_CHECKING, Any

from starpulse.board.model.board_feed import BoardFeed
from starpulse.event_log.wake import StopEvent
from starpulse.pulls.adapters.outbound.pull_requests import PULL_URL, GhUnavailableError, query_github
from starpulse.pulls.model import required as rulesets
from starpulse.pulls.model.pins import Repo

if TYPE_CHECKING:  # annotation only: the pull store opens the database stack
    from starpulse.pulls.adapters.outbound.pulls import PullStore

logger = logging.getLogger(__name__)

#: The waits before a failed single-PR read is asked again: a minute of GitHub trouble, then up to a quarter hour.
RETRY_DELAYS_S = (15.0, 45.0, 120.0, 300.0, 600.0)
#: A required check's result, by the `conclusion` of a check run or the `state` of a commit status.
_PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_RUNNING = {"IN_PROGRESS", "QUEUED", "WAITING", "PENDING", "REQUESTED", "EXPECTED"}


def _selection(number: int) -> str:
    """The alias reading PR `number`: its facts, its required checks at the head commit and its review threads."""
    return f"""
  p{number}: pullRequest(number: {number}) {{
    number state isDraft isInMergeQueue mergeable baseRefName headRefName headRefOid title body updatedAt createdAt mergedAt
    mergeCommit {{ oid }}
    files(first: 100) {{ totalCount pageInfo {{ hasNextPage endCursor }} nodes {{ path }} }}
    headRef {{ compare(headRef: "main") {{ aheadBy }} }}
    ciCommits: commits(last: 100) {{ nodes {{ commit {{ oid
      checkSuites(first: 20) {{ nodes {{ status conclusion createdAt updatedAt workflowRun {{ runAttempt }} }} }} }} }} }}
    timelineItems(first: 100, itemTypes: [HEAD_REF_FORCE_PUSHED_EVENT]) {{
      nodes {{ ... on HeadRefForcePushedEvent {{ createdAt afterCommit {{ oid }} }} }}
    }}
    commits(last: 1) {{ nodes {{ commit {{ statusCheckRollup {{ contexts(first: 100) {{ nodes {{
      __typename
      ... on CheckRun {{ name status conclusion isRequired(pullRequestNumber: {number}) }}
      ... on StatusContext {{ context state isRequired(pullRequestNumber: {number}) }}
    }} }} }} }} }} }}
    reviewThreads(first: 100) {{ nodes {{ id isResolved comments(first: 1) {{ nodes {{ author {{ login }} }} }} }} }}
  }}"""


def _query(numbers: Iterable[int]) -> str:
    selections = "".join(_selection(number) for number in numbers)
    return (
        "query($owner: String!, $name: String!) { rateLimit { cost remaining resetAt } "
        f"repository(owner: $owner, name: $name) {{{rulesets.SELECTION}{selections}\n}} }}"
    )


def _result(check: dict) -> str:
    """`pass`, `failing` or `pending` for one check run or commit status."""
    outcome = check.get("conclusion") or check.get("status") or check["state"]
    if outcome in _PASSED:
        return "pass"
    return "pending" if outcome in _RUNNING else "failing"


def _paths(files: dict) -> list[str] | None:
    """The changed paths the read returned, None when it returned fewer than the pull request's `totalCount`."""
    paths = [file["path"] for file in files["nodes"]]
    return paths if files["totalCount"] <= len(paths) else None


def _record(repo: str, node: dict, now: float, wanted: Iterable[str] = ()) -> dict[str, Any]:
    """The served record of one `pullRequest` node, its required checks reduced to a rollup; a context in `wanted` that
    no check on the head carries is a required check with result `missing`."""
    head = next(iter(node["commits"]["nodes"]), None)  # a PR can hold no commits: record it with an empty rollup
    rollup = (head and head["commit"]["statusCheckRollup"]) or {"contexts": {"nodes": []}}
    posted = [check for check in rollup["contexts"]["nodes"] if check]  # GitHub can return a null node in a connection
    required = rulesets.with_missing(
        [
            {"name": check.get("name") or check["context"], "result": _result(check)}
            for check in posted
            if check.get("isRequired")
        ],
        (check.get("name") or check["context"] for check in posted),
        wanted,
    )
    unresolved = [
        {"id": thread["id"], "author": ((thread["comments"]["nodes"] or [{}])[0].get("author") or {}).get("login")}
        for thread in node["reviewThreads"]["nodes"]
        if not thread["isResolved"]
    ]
    results = {"pending" if check["result"] == "missing" else check["result"] for check in required}
    checks = next((name for name in ("failing", "pending", "pass") if name in results), "none")
    return {
        "repo": repo,
        "number": node["number"],
        "state": node["state"],
        "isDraft": node["isDraft"],
        "mergeable": node["mergeable"],
        "baseRefName": node["baseRefName"],
        "headRefOid": node["headRefOid"],
        "title": node.get("title", ""),
        "body": node["body"] or "",
        "checks": checks,
        "requiredChecks": required,
        "threads": len(unresolved),
        "unresolvedThreads": unresolved,
        "headRefName": node["headRefName"],
        "updatedAt": node["updatedAt"],
        "mergedAt": node["mergedAt"],
        "mergeSha": (node["mergeCommit"] or {}).get("oid"),
        "fetchedAt": now,
        "detail": {
            "mergedAt": node["mergedAt"],
            "mergeSha": (node["mergeCommit"] or {}).get("oid"),
            "behindMain": ((node["headRef"] or {}).get("compare") or {}).get("aheadBy"),
            "queued": bool(node.get("isInMergeQueue")),
            "files": _paths(node["files"]),
            "ci": {  # the parts of the node `ci_trail.parse` reads
                "createdAt": node["createdAt"],
                "mergeable": node["mergeable"],
                "merged": node["state"] == "MERGED",
                "mergedAt": node["mergedAt"],
                "commits": node["ciCommits"],
                "timelineItems": node["timelineItems"],
            },
        },
    }


def _all_files(repo: str, node: dict, graphql: Callable[[str, str], dict]) -> dict:
    """`node`'s `files` connection with every later page read, 100 paths per request."""
    files = node["files"]
    while files["pageInfo"]["hasNextPage"]:
        number = node["number"]
        cursor = files["pageInfo"]["endCursor"]
        page = graphql(
            repo,
            f'query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ p{number}: pullRequest(number: {number}) {{ files(first: 100, after: "{cursor}") {{ totalCount pageInfo {{ hasNextPage endCursor }} nodes {{ path }} }} }} }} }}',
        )[f"p{number}"]["files"]
        files = {**page, "nodes": files["nodes"] + page["nodes"]}
    return files


def refresh_pull(
    repo: str, number: int, store: PullStore, now: float, graphql: Callable[[str, str], dict] = query_github
) -> dict[str, Any] | None:
    """Read pull request `number` of `repo` alone, one request, and save its record, which it returns; a number
    GitHub has none for leaves the store as it was and returns None."""
    read = graphql(repo, _query([number]))
    if node := read[f"p{number}"]:
        node["files"] = _all_files(repo, node, graphql)
        record = _record(repo, node, now, rulesets.contexts(read, node["baseRefName"]))
        store.save([record])
        return record
    return None


class PullSync:
    """Reads the pull requests named to `request` from GitHub, each alone on this thread as soon as it is asked for,
    and hands the Board its tasks' pull requests after each (`project`, `PullRequests.refresh`). The events keep
    the store current between those reads. Setting `stop` ends the loops `serve_forever` runs."""

    def __init__(
        self,
        store: PullStore,
        feed: BoardFeed,
        repos: Sequence[Repo] = (),
        graphql: Callable[[str, str], dict] = query_github,
        clock: Callable[[], float] = time.time,
        project: Callable[[], None] | None = None,
        stop: StopEvent | None = None,
        retry_delays: Sequence[float] = RETRY_DELAYS_S,
    ) -> None:
        self._store = store
        self._feed = feed
        self._repos = repos
        self._graphql = graphql
        self._clock = clock
        self._project = project
        self._stop = stop or StopEvent()
        #: The reads waiting, each pull request once, as ordered sets: the asks of a page or a delivery (`urgent`) first.
        self._urgent: dict[tuple[str, int], None] = {}
        self._queued: dict[tuple[str, int], None] = {}
        self._waiting = threading.Lock()
        self._wake = threading.Event()
        self._projection = threading.Event()
        self._projecting = False
        self._retry_delays = retry_delays
        self._attempts: dict[tuple[str, int], int] = {}
        self._retrying: list[tuple[float, str, int]] = []

    def _linked(self) -> dict[str, set[int]]:
        """The numbers the open tasks' PR links name, by repository."""
        linked: dict[str, set[int]] = {}
        for prs in self._feed.pull_requests().values():
            for url in prs:
                if match := PULL_URL.fullmatch(url):
                    linked.setdefault(match[1], set()).add(int(match[2]))
        return linked

    def tracked(self) -> list[str]:
        """The repositories to read: those the open tasks' PR links and the store name, and each `[[repos]]` entry
        under an owner a link names."""
        linked = set(self._linked())
        owners = {repo.split("/")[0] for repo in linked}
        pinned = {f"{owner}/{repo.name}" for owner in owners for repo in self._repos}
        return sorted(linked | pinned | set(self._store.repos()))

    def request(self, repo: str, number: int, *, urgent: bool = False) -> bool:
        """Queue a read of pull request `number` of `repo` for the refresh thread to serve now; False, queueing
        nothing, for a repository this store does not track. A pull request already waiting is not queued twice, and an
        `urgent` one (a delivery's ask) is read before every other waiting one, which the events' rereads are."""
        if repo not in self.tracked():
            return False
        self._put((repo, number), urgent)
        self._wake.set()
        return True

    def _put(self, key: tuple[str, int], urgent: bool = False) -> None:
        with self._waiting:
            if urgent:
                self._queued.pop(key, None)
                self._urgent[key] = None
            elif key not in self._urgent:
                self._queued[key] = None

    def _take(self) -> tuple[str, int] | None:
        with self._waiting:
            for waiting in (self._urgent, self._queued):
                for key in waiting:
                    del waiting[key]
                    return key
        return None

    def _retry(self, repo: str, number: int) -> None:
        """Ask for the read again after the next of `retry_delays`; a read that failed them all is left, for the
        pull request's next event or `pr_status --live`."""
        tried = self._attempts.get((repo, number), 0)
        if tried >= len(self._retry_delays):
            self._attempts.pop((repo, number), None)
            return
        self._attempts[repo, number] = tried + 1
        self._retrying.append((self._clock() + self._retry_delays[tried], repo, number))

    def next_retry_in(self) -> float | None:
        """Seconds until the earliest failed read is asked again; none when no read waits."""
        return max(0.0, min(due for due, _, _ in self._retrying) - self._clock()) if self._retrying else None

    def _requeue_due(self) -> None:
        now = self._clock()
        for due, repo, number in [entry for entry in self._retrying if entry[0] <= now]:
            self._retrying.remove((due, repo, number))
            self._put((repo, number))

    def _read_requests(self) -> bool:
        """Read each queued pull request alone, and say whether any was queued; one that cannot be read is logged
        and asked again later (`_retry`), as is an open one whose `mergeable` GitHub has not yet computed."""
        self._requeue_due()
        served = False
        while True:
            if (key := self._take()) is None:
                break
            repo, number = key
            served = True
            try:
                record = refresh_pull(repo, number, self._store, self._clock(), self._graphql)
                if record and record["state"] == "OPEN" and record["mergeable"] == "UNKNOWN":
                    self._retry(repo, number)  # GitHub computes mergeability lazily after a push: ask again
                else:
                    self._attempts.pop((repo, number), None)
            except GhUnavailableError as exc:
                logger.warning("pull requests: %s", exc)
                self._retry(repo, number)
            except Exception:  # one request's bad answer must not end the refresh thread
                logger.exception("pull requests: %s#%d failed to refresh", repo, number)
                self._retry(repo, number)
        return served

    def serve_requests(self) -> None:
        """Read each queued pull request alone, then project once."""
        if self._read_requests():
            self.project()

    def project(self) -> None:
        """Hand the Board its tasks' pull requests from the store; a failure is logged, never ends the thread.
        Once `serve_forever` has started the projection thread this only asks it for a projection."""
        if self._projecting:
            self._projection.set()
        else:
            self._project_now()

    def _project_now(self) -> None:
        if self._project:
            try:
                self._project()
            except Exception:
                logger.exception("pull requests: the Board's pull requests failed to project")

    def _project_forever(self) -> None:  # pragma: no mutate block — timer loop
        """Project whenever asked, asks made meanwhile coalescing into one run."""
        while not self._stop.is_set():
            self._projection.wait()
            self._projection.clear()
            if not self._stop.is_set():
                self._project_now()

    def _wake_on_stop(self) -> None:  # pragma: no mutate block — timer loop
        """Wake the loops that wait on an event of their own once `stop` is set."""
        self._stop.wait()
        self._wake.set()
        self._projection.set()

    def serve_forever(self) -> None:  # pragma: no mutate block — timer loop
        """Once the Board replay is done, so the first projection sees every task, project what the store already
        holds, then serve each refresh asked for until `stop`. No timer reads a pull request: a webhook asks for each
        read, and the sweeper's `github` kind recovers a fact no webhook delivered. Projection runs on its own thread:
        a cold pin memo makes it walk hundreds of `gh` reads, and a refresh must not wait behind that."""
        self._feed.wait_replayed()
        if not self._projecting:  # a run restarted after a crash keeps the helper threads the first one started
            self._projecting = True
            threading.Thread(target=self._wake_on_stop, name="pull-stop", daemon=True).start()
            threading.Thread(target=self._project_forever, name="pull-project", daemon=True).start()
        self.project()
        while not self._stop.is_set():
            self._wake.wait(self.next_retry_in())
            self._wake.clear()  # before the drain: a request queued after it sets the event again
            self.serve_requests()
