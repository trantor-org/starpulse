"""Each open task's pull requests, read from GitHub on a timer and carried in the snapshot.

The Board's tasks cite their pull requests as links; nothing on the projection says whether a PR's checks pass,
whether it merged or how many review threads are open. `fetch` asks GitHub for that (one `gh api graphql` request
per repository, however many PRs it holds), and `PullRequests` keeps the answer in the feed so a snapshot is served
from memory and never waits on GitHub. When GitHub cannot be reached for any repository the last answer stays, marked `stale`.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from collections.abc import Callable, Collection
from itertools import groupby

from starpulse.board_feed import BoardFeed

logger = logging.getLogger(__name__)

#: Seconds between reads of GitHub.
REFRESH_S = 60.0
_GH_TIMEOUT_S = 30
_PULL = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)/?")
#: GitHub's `StatusState` for a head commit's check rollup, as the page names it; no rollup at all is `none`.
_CHECKS = {"SUCCESS": "pass", "FAILURE": "failing", "ERROR": "failing", "PENDING": "pending", "EXPECTED": "pending"}
_FRAGMENT = """
fragment Pull on PullRequest {
  number
  merged
  commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
  reviewThreads(first: 100) { nodes { isResolved } }
}
"""


class GhUnavailableError(Exception):
    """GitHub could not be read: `gh` is missing, refused, timed out or answered something unreadable."""


def read_repository(repo: str, numbers: list[int]) -> dict:
    """The GraphQL `repository` node holding each of `numbers` as `p<number>`, through `gh`."""
    owner, name = repo.split("/")
    pulls = " ".join(f"p{number}: pullRequest(number: {number}) {{ ...Pull }}" for number in numbers)
    query = (
        f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {pulls} }} }}{_FRAGMENT}"
    )
    command = ["gh", "api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=_GH_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GhUnavailableError(str(exc)) from exc
    try:  # gh exits non-zero for a PR GraphQL cannot find but still prints the others, so read before judging the exit
        repository = json.loads(result.stdout)["data"]["repository"]
    except (ValueError, KeyError, TypeError) as exc:
        raise GhUnavailableError(result.stderr.strip() or f"gh exited {result.returncode}") from exc
    if repository is None:
        raise GhUnavailableError(f"{repo} is not readable")
    return repository


def _read_pulls(
    repo: str, wanted: list[tuple[str, int, str]], read: Callable[[str, list[int]], dict]
) -> dict[str, dict]:
    """One repository's records by URL; a PR GitHub does not return is left out."""
    nodes = read(repo, [number for _, number, _ in wanted])
    out: dict[str, dict] = {}
    try:
        for _, number, url in wanted:
            if node := nodes.get(f"p{number}"):
                rollup = node["commits"]["nodes"][0]["commit"]["statusCheckRollup"]
                out[url] = {
                    "number": node["number"],
                    "url": url,
                    "checks": _CHECKS.get(rollup["state"], "none") if rollup else "none",
                    "merged": node["merged"],
                    "threads": sum(not thread["isResolved"] for thread in node["reviewThreads"]["nodes"]),
                    "stale": False,
                }
    except (KeyError, IndexError, TypeError) as exc:
        raise GhUnavailableError(f"unexpected GraphQL answer for {repo}: {exc!r}") from exc
    return out


def fetch(urls: Collection[str], read: Callable[[str, list[int]], dict] = read_repository) -> dict[str, dict]:
    """Each URL's `{number, url, checks, merged, threads, stale}`; a URL GitHub does not return is left out.

    `checks` is `pass`, `failing`, `pending` or `none`; `threads` counts the unresolved review threads. A
    repository GitHub cannot read is logged and left out so the others still answer; only when every repository
    fails does the read raise `GhUnavailableError`, for `PullRequests.refresh` to keep its last answer.
    """
    pulls = sorted((m[1], int(m[2]), url) for url in urls if (m := _PULL.fullmatch(url)))
    out: dict[str, dict] = {}
    failures: list[GhUnavailableError] = []
    groups = [(repo, list(group)) for repo, group in groupby(pulls, key=lambda pull: pull[0])]
    for repo, wanted in groups:
        try:
            out |= _read_pulls(repo, wanted, read)
        except GhUnavailableError as exc:
            logger.warning("pull requests: %s", exc)
            failures.append(exc)
    if groups and len(failures) == len(groups):
        raise failures[0]
    return out


class PullRequests:
    """Keeps `feed`'s per-task pull request state current from `fetch`, the last good answer held between reads."""

    def __init__(self, feed: BoardFeed, fetch: Callable[[Collection[str]], dict[str, dict]] = fetch) -> None:
        self._feed = feed
        self._fetch = fetch
        self._last: dict[str, dict] = {}

    def refresh(self) -> None:
        """Read every open task's PRs once; on failure the last answer stays, every PR marked `stale`."""
        wanted = self._feed.pull_requests()
        urls = list(dict.fromkeys(url for prs in wanted.values() for url in prs))
        try:
            self._last = self._fetch(urls) if urls else {}
        except GhUnavailableError as exc:
            logger.warning("pull requests: %s", exc)
            self._last = {url: {**pull, "stale": True} for url, pull in self._last.items()}
        held = {task: [self._last[url] for url in prs if url in self._last] for task, prs in wanted.items()}
        self._feed.set_pulls({task: pulls for task, pulls in held.items() if pulls})

    def run_forever(self, interval_s: float = REFRESH_S) -> None:  # pragma: no mutate block — timer loop
        while True:
            self.refresh()
            time.sleep(interval_s)
