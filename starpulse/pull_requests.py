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
from collections.abc import Callable, Collection, Mapping, Sequence
from itertools import groupby
from types import MappingProxyType
from typing import Protocol

from starpulse.board_feed import BoardFeed
from starpulse.ci_trail import PullHistory, parse
from starpulse.config import Repo
from starpulse.pins import GitHub, Pins, link

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
  mergedAt
  mergeCommit { oid }
  createdAt
  mergeable
  commits(last: 100) { nodes { commit { oid statusCheckRollup { state } checkSuites(first: 20) { nodes { status conclusion createdAt updatedAt workflowRun { runAttempt } } } } } }
  timelineItems(first: 100, itemTypes: [HEAD_REF_FORCE_PUSHED_EVENT]) { nodes { ... on HeadRefForcePushedEvent { createdAt afterCommit { oid } } } }
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
) -> tuple[dict[str, dict], dict[str, PullHistory]]:
    """One repository's records and CI histories by URL; a PR GitHub does not return is left out."""
    nodes = read(repo, [number for _, number, _ in wanted])
    out: dict[str, dict] = {}
    history: dict[str, PullHistory] = {}
    try:
        for _, number, url in wanted:
            if node := nodes.get(f"p{number}"):
                rollup = node["commits"]["nodes"][-1]["commit"]["statusCheckRollup"]
                out[url] = {
                    "number": node["number"],
                    "url": url,
                    "checks": _CHECKS.get(rollup["state"], "none") if rollup else "none",
                    "merged": node["merged"],
                    "merge_sha": (node["mergeCommit"] or {}).get("oid"),
                    "merged_at": node["mergedAt"],
                    "threads": sum(not thread["isResolved"] for thread in node["reviewThreads"]["nodes"]),
                    "stale": False,
                }
                history[url] = parse(url, node)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise GhUnavailableError(f"unexpected GraphQL answer for {repo}: {exc!r}") from exc
    return out, history


class Pulls(dict[str, dict]):
    """A `fetch` answer: the records read, `unread`, the URLs of repositories GitHub could not be asked about, and
    `history`, what GitHub dates of each record's CI."""

    unread: frozenset[str] = frozenset()
    history: Mapping[str, PullHistory] = MappingProxyType({})


def fetch(urls: Collection[str], read: Callable[[str, list[int]], dict] = read_repository) -> Pulls:
    """Each URL's `{number, url, checks, merged, merge_sha, merged_at, threads, stale}`; a URL GitHub does not return is left out.

    `checks` is `pass`, `failing`, `pending` or `none`; `threads` counts the unresolved review threads; `merge_sha` and
    `merged_at` (ISO 8601 UTC) are the merge commit and merge time of a merged PR and `None` for an open one. A
    repository GitHub cannot read is logged, left out and named in `unread` so the others still answer; only when every repository
    fails does the read raise `GhUnavailableError`, for `PullRequests.refresh` to keep its last answer.
    """
    pulls = sorted((m[1], int(m[2]), url) for url in urls if (m := _PULL.fullmatch(url)))
    out = Pulls()
    history: dict[str, PullHistory] = {}
    unread: set[str] = set()
    failures: list[GhUnavailableError] = []
    groups = [(repo, list(group)) for repo, group in groupby(pulls, key=lambda pull: pull[0])]
    for repo, wanted in groups:
        try:
            records, dated = _read_pulls(repo, wanted, read)
            out |= records
            history |= dated
        except GhUnavailableError as exc:
            logger.warning("pull requests: %s", exc)
            failures.append(exc)
            unread.update(url for _, _, url in wanted)
    if groups and len(failures) == len(groups):
        raise failures[0]
    out.unread = frozenset(unread)
    out.history = history
    return out


class CiRecorder(Protocol):
    """Takes each task's pull request histories after a read, to record as the task's CI trail."""

    def record(self, pulls: Mapping[str, Sequence[PullHistory]]) -> None: ...


class PullRequests:
    """Keeps `feed`'s per-task pull request state current from `fetch`, the last good answer held between reads, and
    hands each read's histories to `trail` when there is one."""

    def __init__(
        self,
        feed: BoardFeed,
        fetch: Callable[[Collection[str]], Pulls] = fetch,
        repos: Sequence[Repo] = (),
        pins: Pins | None = None,
        trail: CiRecorder | None = None,
    ) -> None:
        self._feed = feed
        self._fetch = fetch
        self._repos = repos
        self._pins = pins or GitHub()
        self._trail = trail
        self._last: dict[str, dict] = {}

    def refresh(self) -> None:
        """Read every open task's PRs once; a PR GitHub could not be asked about keeps its last record, marked `stale`."""
        wanted = self._feed.pull_requests()
        urls = list(dict.fromkeys(url for prs in wanted.values() for url in prs))
        try:
            fresh = self._fetch(urls) if urls else Pulls()
            kept = {url: {**self._last[url], "stale": True} for url in fresh.unread if url in self._last}
            self._last = {**fresh, **kept}
            if self._trail:
                self._trail.record(
                    {task: [fresh.history[url] for url in prs if url in fresh.history] for task, prs in wanted.items()}
                )
        except GhUnavailableError as exc:
            logger.warning("pull requests: %s", exc)
            self._last = {url: {**pull, "stale": True} for url, pull in self._last.items()}
        if self._repos:
            self._last = link(self._last, self._repos, self._pins.pointer, self._pins.reaches)
        held = {task: [self._last[url] for url in prs if url in self._last] for task, prs in wanted.items()}
        self._feed.set_pulls({task: pulls for task, pulls in held.items() if pulls}, self.answers())

    def answers(self) -> dict:
        """The records and pin answers read so far, for the feed to save with the Board."""
        pins = self._pins.answers() if isinstance(self._pins, GitHub) else {}
        return {"records": self._last, "pins": pins}

    def restore(self) -> None:
        """Start from the answers the feed resumed with (`BoardFeed.pull_answers`), so a restart reads GitHub warm."""
        saved = self._feed.pull_answers()
        self._last = {**saved.get("records", {}), **self._last}
        if isinstance(self._pins, GitHub):
            self._pins.restore(saved.get("pins", {}))

    def run_forever(self, interval_s: float = REFRESH_S) -> None:  # pragma: no mutate block — timer loop
        """Refresh once the Board replay is done, so the first read sees every task, then every `interval_s`."""
        self._feed.wait_replayed()
        self.restore()
        while True:
            self.refresh()
            time.sleep(interval_s)
