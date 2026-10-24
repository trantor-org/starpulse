"""Each open task's pull requests, projected from the PR store and carried in the snapshot.

The Board's tasks cite their pull requests as links; nothing on the projection says whether a PR's checks pass,
whether it merged or how many review threads are open. The PR store (`pull_store`) is the one reader of GitHub: it
keeps, for each pull request, those facts and the detail the Board needs beside them (merge commit and time, commits
behind main, changed files and the CI history). `PullRequests` reads the records of the PRs open tasks cite from the
store, never from GitHub, and keeps them in the feed so a snapshot is served from memory. For the pin bumps of
`[[repos]]`, `pins.link` finds the parent merge that applies each child merge. A record is current until a newer
event lands, so `stale` is always false; its `fetchedAt` is the time of the last event that touched it.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Protocol

from starpulse._internal.ci.ci_trail import PullHistory, parse
from starpulse._internal.config.config import Repo
from starpulse._internal.config.pins import GitHub, Pins, link
from starpulse._internal.feed.board_feed import BoardFeed

if TYPE_CHECKING:  # annotation only: the pull store opens the database stack
    from starpulse._internal.pulls.pulls import PullStore

logger = logging.getLogger(__name__)

_GH_TIMEOUT_S = 30
PULL_URL = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)/?")


class GhUnavailableError(Exception):
    """GitHub could not be read: `gh` is missing, refused, timed out or answered something unreadable."""


def query_github(repo: str, query: str) -> dict:
    """The `repository` node `query` (one `gh api graphql` request about `repo`, which names `$owner` and `$name`) returns.

    The request's `rateLimit` cost is logged. Raises `GhUnavailableError` when `gh` fails or answers nothing readable.
    """
    owner, name = repo.split("/")
    # the query rides stdin: a many-PR query outgrows the 128 KB limit on one argument
    body = json.dumps({"query": query, "variables": {"owner": owner, "name": name}})
    try:
        result = subprocess.run(
            ["gh", "api", "graphql", "--input", "-"], input=body, capture_output=True, text=True, timeout=_GH_TIMEOUT_S
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GhUnavailableError(str(exc)) from exc
    try:  # gh exits non-zero for a PR GraphQL cannot find but still prints the others, so read before judging the exit
        data = json.loads(result.stdout)["data"]
        repository = data["repository"]
    except (ValueError, KeyError, TypeError) as exc:
        raise GhUnavailableError(result.stderr.strip() or f"gh exited {result.returncode}") from exc
    if rate := data.get("rateLimit"):
        logger.info(
            "pull requests: %s query cost %s, remaining %s, resets %s",
            repo,
            rate.get("cost"),
            rate.get("remaining"),
            rate.get("resetAt"),
        )
    if repository is None:
        raise GhUnavailableError(f"{repo} is not readable")
    return repository


class CiRecorder(Protocol):
    """Takes each task's pull request histories after a read, to record as the task's CI trail."""

    def record(self, pulls: Mapping[str, Sequence[PullHistory]]) -> None: ...


class PullRequests:
    """Keeps `feed`'s per-task pull request state current from `store`, and hands each read's histories to `trail`
    when there is one."""

    def __init__(
        self,
        feed: BoardFeed,
        store: PullStore,
        repos: Sequence[Repo] = (),
        pins: Pins | None = None,
        trail: CiRecorder | None = None,
    ) -> None:
        self._feed = feed
        self._store = store
        self._repos = repos
        self._pins = pins or GitHub(lambda: feed.pull_answers().get("pins", {}))
        self._trail = trail
        self._last: dict[str, dict] = {}

    def _stored(self, urls: Sequence[str]) -> dict[str, dict]:
        """The store's record of each URL it holds with its detail; a PR it does not hold, or holds from before it
        kept detail, is left out until the store reads it."""
        found = {}
        for url in urls:
            if match := PULL_URL.fullmatch(url):
                records = self._store.find(repo=match[1], number=int(match[2]), detailed=True)
                if records and records[0]["detail"]:
                    found[url] = records[0]
        return found

    def refresh(self) -> None:
        """Project every open task's PRs from the store once."""
        wanted = self._feed.pull_requests()
        stored = self._stored(list(dict.fromkeys(url for prs in wanted.values() for url in prs)))
        self._last = {
            url: {
                "number": record["number"],
                "repo": record["repo"],
                "url": url,
                "checks": record["checks"],
                "merged": record["state"] == "MERGED",
                "merge_sha": record["detail"]["mergeSha"],
                "merged_at": record["detail"]["mergedAt"],
                "files": record["detail"]["files"],
                "threads": record["threads"],
                "behind_main": record["detail"]["behindMain"],
                "stale": False,
            }
            for url, record in stored.items()
        }
        if self._repos:
            self._last = link(self._last, self._repos, self._pins.pointer, self._pins.reaches)
        if self._trail:
            self._trail.record(
                {
                    task: [parse(url, stored[url]["detail"]["ci"]) for url in prs if url in stored]
                    for task, prs in wanted.items()
                }
            )
        held = {task: [self._last[url] for url in prs if url in self._last] for task, prs in wanted.items()}
        self._feed.set_pulls({task: pulls for task, pulls in held.items() if pulls}, self.answers())

    def answers(self) -> dict:
        """The records and pin answers read so far, for the feed to save with the Board."""
        pins = self._pins.answers() if isinstance(self._pins, GitHub) else {}
        return {"records": self._last, "pins": pins}
