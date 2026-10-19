"""The single-pull-request read behind `POST /api/pulls/refresh`, and the thread that serves it.

The PR store is a projection of lifecycle events (`starpulse._internal.pulls.pull_events`); nothing here polls GitHub.
`refresh_pull` reads one pull request alone (its facts, required checks at the head commit and review threads, one
`query_github`) and replaces its record, for the manual read of `pr_status --live` and for a pull request a close
event relays (`PullSync.request`). `isRequired` takes the PR's number, so a required check can only be read through
`pullRequest(number:)`.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from typing import TYPE_CHECKING, Any

from starpulse._internal.config.config import Repo
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.pulls.pull_requests import PULL_URL, GhUnavailableError, query_github

if TYPE_CHECKING:  # annotation only: the pull store opens the database stack
    from starpulse._internal.pulls.pulls import PullStore

logger = logging.getLogger(__name__)

#: A required check's result, by the `conclusion` of a check run or the `state` of a commit status.
_PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_RUNNING = {"IN_PROGRESS", "QUEUED", "WAITING", "PENDING", "REQUESTED", "EXPECTED"}


def _selection(number: int) -> str:
    """The alias reading PR `number`: its facts, its required checks at the head commit and its review threads."""
    return f"""
  p{number}: pullRequest(number: {number}) {{
    number state isDraft mergeable baseRefName headRefName headRefOid body updatedAt createdAt mergedAt
    mergeCommit {{ oid }}
    files(first: 100) {{ nodes {{ path }} }}
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
        f"repository(owner: $owner, name: $name) {{{selections}\n}} }}"
    )


def _result(check: dict) -> str:
    """`pass`, `failing` or `pending` for one check run or commit status."""
    outcome = check.get("conclusion") or check.get("status") or check["state"]
    if outcome in _PASSED:
        return "pass"
    return "pending" if outcome in _RUNNING else "failing"


def _record(repo: str, node: dict, now: float) -> dict[str, Any]:
    """The served record of one `pullRequest` node, its required checks reduced to a rollup."""
    head = next(iter(node["commits"]["nodes"]), None)  # a PR can hold no commits: record it with an empty rollup
    rollup = (head and head["commit"]["statusCheckRollup"]) or {"contexts": {"nodes": []}}
    required = [
        {"name": check.get("name") or check["context"], "result": _result(check)}
        for check in rollup["contexts"]["nodes"]
        if check.get("isRequired")
    ]
    unresolved = [
        {"id": thread["id"], "author": ((thread["comments"]["nodes"] or [{}])[0].get("author") or {}).get("login")}
        for thread in node["reviewThreads"]["nodes"]
        if not thread["isResolved"]
    ]
    results = {check["result"] for check in required}
    checks = next((name for name in ("failing", "pending", "pass") if name in results), "none")
    return {
        "repo": repo,
        "number": node["number"],
        "state": node["state"],
        "isDraft": node["isDraft"],
        "mergeable": node["mergeable"],
        "baseRefName": node["baseRefName"],
        "headRefOid": node["headRefOid"],
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
            "files": [file["path"] for file in node["files"]["nodes"]],
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


def refresh_pull(
    repo: str, number: int, store: PullStore, now: float, graphql: Callable[[str, str], dict] = query_github
) -> None:
    """Read pull request `number` of `repo` alone, one request, and save its record; a number GitHub has none for
    leaves the store as it was."""
    if node := graphql(repo, _query([number]))[f"p{number}"]:
        store.save([_record(repo, node, now)])


class PullSync:
    """Reads the pull requests named to `request` from GitHub, each alone on this thread as soon as it is asked for,
    and hands the Board its tasks' pull requests after each (`project`, `PullRequests.refresh`). The events keep
    the store current between those reads. Setting `stop` ends the loops `run_forever` runs."""

    def __init__(
        self,
        store: PullStore,
        feed: BoardFeed,
        repos: Sequence[Repo] = (),
        graphql: Callable[[str, str], dict] = query_github,
        clock: Callable[[], float] = time.time,
        project: Callable[[], None] | None = None,
        stop: threading.Event | None = None,
    ) -> None:
        self._store = store
        self._feed = feed
        self._repos = repos
        self._graphql = graphql
        self._clock = clock
        self._project = project
        self._stop = stop or threading.Event()
        self._requests: queue.SimpleQueue[tuple[str, int]] = queue.SimpleQueue()
        self._wake = threading.Event()
        self._projection = threading.Event()
        self._projecting = False

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

    def request(self, repo: str, number: int) -> bool:
        """Queue a read of pull request `number` of `repo` for the refresh thread to serve now; False, queueing
        nothing, for a repository this store does not track."""
        if repo not in self.tracked():
            return False
        self._requests.put((repo, number))
        self._wake.set()
        return True

    def reconcile_open(self) -> int:
        """Queue a read of each pull request the store holds OPEN, and say how many: one the retired listing poll left
        open, and no event will close, closes on its read. Each read is one pull request alone, so a clean store costs
        one read per genuinely open pull request."""
        stale = self._store.find(state="OPEN", held_only=True)
        for record in stale:
            self._requests.put((record["repo"], record["number"]))
        if stale:
            self._wake.set()
        return len(stale)

    def _read_requests(self) -> bool:
        """Read each queued pull request alone, and say whether any was queued; one that cannot be read is logged
        and left to the next refresh."""
        served = False
        while True:
            try:
                repo, number = self._requests.get_nowait()
            except queue.Empty:
                break
            served = True
            try:
                refresh_pull(repo, number, self._store, self._clock(), self._graphql)
            except GhUnavailableError as exc:
                logger.warning("pull requests: %s", exc)
            except Exception:  # one request's bad answer must not end the refresh thread
                logger.exception("pull requests: %s#%d failed to refresh", repo, number)
        return served

    def serve_requests(self) -> None:
        """Read each queued pull request alone, then project once."""
        if self._read_requests():
            self.project()

    def project(self) -> None:
        """Hand the Board its tasks' pull requests from the store; a failure is logged, never ends the thread.
        Once `run_forever` has started the projection thread this only asks it for a projection."""
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

    def run_forever(self) -> None:  # pragma: no mutate block — timer loop
        """Once the Board replay is done, so the first projection sees every task, project what the store already
        holds and read each pull request it holds OPEN (`reconcile_open`), then serve each refresh asked for until `stop`. Projection runs on its own thread: a cold pin memo
        makes it walk hundreds of `gh` reads, and a refresh must not wait behind that."""
        threading.Thread(target=self._wake_on_stop, name="pull-stop", daemon=True).start()
        self._feed.wait_replayed()
        self._projecting = True
        threading.Thread(target=self._project_forever, name="pull-project", daemon=True).start()
        self.project()
        self.reconcile_open()
        while not self._stop.is_set():
            self._wake.wait()
            self._wake.clear()  # before the drain: a request queued after it sets the event again
            self.serve_requests()
