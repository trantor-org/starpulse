"""Every open and recently updated pull request of each repository, read in one query and kept in the PR store.

A refresh asks GitHub once per repository (`query_github`, which logs the query's `rateLimit` cost) for the numbers of
every open PR and of the PRs updated most recently, and in the same request for the state of each PR the store holds
open. `isRequired` takes the PR's number, so a required check can only be read through `pullRequest(number:)`, never
inside a listing; a PR the listing shows that the store lacks, or holds in another state, costs one more request, for
itself alone. A check finishing does not change a PR's `updatedAt`, so the open PRs are asked for on every refresh; a
merged or closed PR whose saved record is final is never asked for again (a merged one without its `mergeSha`
is not final yet). No request reads more than `_BATCH` PRs: the rest go in further requests, and each batch of
newly seen PRs is saved as it lands, so a request GitHub refuses or times out on is not repeated with the ones
already read. A repository holding more open PRs than one
listing page (`_PAGE`) is read for the first page only, and says so.
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from collections.abc import Callable, Collection, Iterable, Sequence
from typing import Any

from starpulse._internal.config.config import Repo
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.pulls.pull_requests import PULL_URL, REFRESH_S, GhUnavailableError, query_github
from starpulse._internal.pulls.pulls import PullStore

logger = logging.getLogger(__name__)

_PAGE = 100
#: Merged rows still lacking a merge commit that one refresh reads again, to bound its query cost.
_BACKFILL = 25
#: Pull requests one query reads. GitHub refuses a query of over 500,000 nodes, about 200 selections, charges for one
#: it times out on, and logs no cost for either.
_BATCH = 25
#: A required check's result, by the `conclusion` of a check run or the `state` of a commit status.
_PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_RUNNING = {"IN_PROGRESS", "QUEUED", "WAITING", "PENDING", "REQUESTED", "EXPECTED"}
_LISTING = f"""
  open: pullRequests(states: OPEN, first: {_PAGE}) {{ pageInfo {{ hasNextPage }} nodes {{ number state updatedAt }} }}
  recent: pullRequests(first: {_PAGE}, orderBy: {{field: UPDATED_AT, direction: DESC}}) {{
    nodes {{ number state updatedAt }}
  }}"""


def _selection(number: int) -> str:
    """The alias reading PR `number`: its facts, its required checks at the head commit and its review threads."""
    return f"""
  p{number}: pullRequest(number: {number}) {{
    number state isDraft mergeable baseRefName headRefOid body updatedAt createdAt mergedAt
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
    reviewThreads(first: 100) {{ nodes {{ isResolved }} }}
  }}"""


def _query(numbers: Iterable[int], *, listing: bool) -> str:
    selections = (_LISTING if listing else "") + "".join(_selection(number) for number in numbers)
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
        "threads": sum(not thread["isResolved"] for thread in node["reviewThreads"]["nodes"]),
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


def refresh_repository(
    repo: str,
    store: PullStore,
    now: float,
    graphql: Callable[[str, str], dict] = query_github,
    linked: Collection[int] = (),
) -> None:
    """Bring `store`'s records of `repo` up to date as of epoch `now`; `GhUnavailableError` leaves them as they were.

    `linked` are the numbers open tasks cite: one the store lacks, or holds without its `detail`, is read even when
    the listings do not reach it, as an old merged PR is not."""
    saved = {record["number"]: record for record in store.find(repo=repo, detailed=True)}
    cursor = max((record["updatedAt"] for record in saved.values()), default=None)
    # a merged row saved before the store read the merge commit is read again until it has one, a few per refresh
    backfill = sorted(
        number for number, record in saved.items() if record["state"] == "MERGED" and not record["mergeSha"]
    )
    held = sorted([number for number, record in saved.items() if record["state"] == "OPEN"] + backfill[:_BACKFILL])
    answer = graphql(repo, _query(held[:_BATCH], listing=True))
    if answer["open"]["pageInfo"]["hasNextPage"]:
        logger.warning("pull requests: %s has more than %d open PRs; the rest are not read", repo, _PAGE)
    listed = {item["number"]: item for item in answer["open"]["nodes"] + answer["recent"]["nodes"]}
    unseen = {
        number
        for number, item in listed.items()
        if number not in held
        and saved.get(number, {}).get("state") != item["state"]
        and (item["state"] == "OPEN" or cursor is None or item["updatedAt"] > cursor)
    } | {number for number in linked if number not in held and not saved.get(number, {}).get("detail")}
    nodes = {number: answer[f"p{number}"] for number in held[:_BATCH]}
    for batch in itertools.batched(held[_BATCH:], _BATCH):
        answer = graphql(repo, _query(batch, listing=False))
        nodes |= {number: answer[f"p{number}"] for number in batch}
    # Oldest first and each batch saved as it lands, the held ones last: the cursor is the newest saved `updatedAt`,
    # so a batch that fails is still past it on the next refresh, which asks only for what is left.
    oldest_first = sorted(unseen, key=lambda number: (number not in listed, listed.get(number, {}).get("updatedAt")))
    for batch in itertools.batched(oldest_first, _BATCH):
        answer = graphql(repo, _query(batch, listing=False))
        store.save(_record(repo, answer[f"p{number}"], now) for number in batch if answer[f"p{number}"])
    store.save(_record(repo, node, now) for node in nodes.values() if node)


def refresh_pull(
    repo: str, number: int, store: PullStore, now: float, graphql: Callable[[str, str], dict] = query_github
) -> None:
    """Read pull request `number` of `repo` alone, one request, and save its record; a number GitHub has none for
    leaves the store as it was."""
    if node := graphql(repo, _query([number], listing=False))[f"p{number}"]:
        store.save([_record(repo, node, now)])


class PullSync:
    """Refreshes `store` from GitHub, one query per repository a minute, for every repository worth asking about, and
    after each read hands the Board its tasks' pull requests (`project`, `PullRequests.refresh`). A pull request
    named to `request` is read alone on this same thread, between refreshes, as soon as it is asked for."""

    def __init__(
        self,
        store: PullStore,
        feed: BoardFeed,
        repos: Sequence[Repo] = (),
        graphql: Callable[[str, str], dict] = query_github,
        clock: Callable[[], float] = time.time,
        project: Callable[[], None] | None = None,
    ) -> None:
        self._store = store
        self._feed = feed
        self._repos = repos
        self._graphql = graphql
        self._clock = clock
        self._project = project
        self._requests: queue.SimpleQueue[tuple[str, int]] = queue.SimpleQueue()
        self._wake = threading.Event()

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

    def refresh(self) -> None:
        """Read every tracked repository once; one that cannot be read or parsed is logged and keeps its records.
        Then project the Board's pull requests from the store."""
        linked = self._linked()
        for repo in self.tracked():
            try:
                refresh_repository(repo, self._store, self._clock(), self._graphql, linked.get(repo, ()))
            except GhUnavailableError as exc:
                logger.warning("pull requests: %s", exc)
            except Exception:  # one repository's bad answer must not end the refresh thread
                logger.exception("pull requests: %s failed to refresh", repo)
        self.project()

    def request(self, repo: str, number: int) -> bool:
        """Queue a read of pull request `number` of `repo` for the refresh thread to serve now; False, queueing
        nothing, for a repository this store does not track."""
        if repo not in self.tracked():
            return False
        self._requests.put((repo, number))
        self._wake.set()
        return True

    def serve_requests(self) -> None:
        """Read each queued pull request alone, then project once; one that cannot be read is logged and left to the
        next refresh."""
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
        if served:
            self.project()

    def _idle(self, seconds: float) -> None:  # pragma: no mutate block — timer loop
        """Wait `seconds` for the next refresh, serving each request as it arrives."""
        deadline = time.monotonic() + seconds
        while (left := deadline - time.monotonic()) > 0:
            self._wake.wait(left)
            self._wake.clear()  # before the drain: a request queued after it sets the event again
            self.serve_requests()

    def project(self) -> None:
        """Hand the Board its tasks' pull requests from the store; a failure is logged, never ends the thread."""
        if self._project:
            try:
                self._project()
            except Exception:
                logger.exception("pull requests: the Board's pull requests failed to project")

    def run_forever(self, interval_s: float = REFRESH_S) -> None:  # pragma: no mutate block — timer loop
        """Once the Board replay is done, so the first projection sees every task, project what the store already
        holds, then refresh every `interval_s`."""
        self._feed.wait_replayed()
        self.project()
        while True:
            self.refresh()
            self._idle(interval_s)
