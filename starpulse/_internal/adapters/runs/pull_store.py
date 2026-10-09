"""Every open and recently updated pull request of each repository, read in one query and kept in the PR store.

A refresh asks GitHub once per repository (`query_github`, which logs the query's `rateLimit` cost) for the numbers of
every open PR and of the PRs updated most recently, and in the same request for the state of each PR the store holds
open. `isRequired` takes the PR's number, so a required check can only be read through `pullRequest(number:)`, never
inside a listing; a PR the listing shows that the store lacks, or holds in another state, costs one more request, for
itself alone. A check finishing does not change a PR's `updatedAt`, so the open PRs are asked for on every refresh; a
merged or closed PR whose saved record is final is never asked for again. A repository holding more open PRs than one
listing page (`_PAGE`) is read for the first page only, and says so.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from starpulse._internal.adapters.runs.pull_requests import PULL_URL, REFRESH_S, GhUnavailableError, query_github
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.config.config import Repo
from starpulse._internal.adapters.runs.pulls import PullStore

logger = logging.getLogger(__name__)

_PAGE = 100
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
    number state isDraft mergeable baseRefName headRefOid body updatedAt
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
    rollup = node["commits"]["nodes"][-1]["commit"]["statusCheckRollup"] or {"contexts": {"nodes": []}}
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
        "fetchedAt": now,
    }


def refresh_repository(
    repo: str, store: PullStore, now: float, graphql: Callable[[str, str], dict] = query_github
) -> None:
    """Bring `store`'s records of `repo` up to date as of epoch `now`; `GhUnavailableError` leaves them as they were."""
    saved = {record["number"]: record for record in store.find(repo=repo)}
    cursor = max((record["updatedAt"] for record in saved.values()), default=None)
    held = sorted(number for number, record in saved.items() if record["state"] == "OPEN")
    answer = graphql(repo, _query(held, listing=True))
    if answer["open"]["pageInfo"]["hasNextPage"]:
        logger.warning("pull requests: %s has more than %d open PRs; the rest are not read", repo, _PAGE)
    nodes = {number: answer[f"p{number}"] for number in held}
    unseen = sorted(
        {
            item["number"]
            for item in answer["open"]["nodes"] + answer["recent"]["nodes"]
            if item["number"] not in nodes
            and saved.get(item["number"], {}).get("state") != item["state"]
            and (item["state"] == "OPEN" or cursor is None or item["updatedAt"] > cursor)
        }
    )
    if unseen:
        answer = graphql(repo, _query(unseen, listing=False))
        nodes |= {number: answer[f"p{number}"] for number in unseen}
    store.save(_record(repo, node, now) for node in nodes.values() if node)


class PullSync:
    """Refreshes `store` from GitHub, one query per repository a minute, for every repository worth asking about."""

    def __init__(
        self,
        store: PullStore,
        feed: BoardFeed,
        repos: Sequence[Repo] = (),
        graphql: Callable[[str, str], dict] = query_github,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._feed = feed
        self._repos = repos
        self._graphql = graphql
        self._clock = clock

    def tracked(self) -> list[str]:
        """The repositories to read: those the open tasks' PR links and the store name, and each `[[repos]]` entry
        under an owner a link names."""
        linked = {
            match[1] for prs in self._feed.pull_requests().values() for url in prs if (match := PULL_URL.fullmatch(url))
        }
        owners = {repo.split("/")[0] for repo in linked}
        pinned = {f"{owner}/{repo.name}" for owner in owners for repo in self._repos}
        return sorted(linked | pinned | set(self._store.repos()))

    def refresh(self) -> None:
        """Read every tracked repository once; one that cannot be read is logged and keeps its records."""
        for repo in self.tracked():
            try:
                refresh_repository(repo, self._store, self._clock(), self._graphql)
            except GhUnavailableError as exc:
                logger.warning("pull requests: %s", exc)

    def run_forever(self, interval_s: float = REFRESH_S) -> None:  # pragma: no mutate block — timer loop
        """Refresh once the Board replay is done, so the first read sees every task, then every `interval_s`."""
        self._feed.wait_replayed()
        while True:
            self.refresh()
            time.sleep(interval_s)
