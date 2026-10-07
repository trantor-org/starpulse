"""Each open task's pull requests, read from GitHub on a timer and carried in the snapshot.

The Board's tasks cite their pull requests as links; nothing on the projection says whether a PR's checks pass,
whether it merged or how many review threads are open. `fetch` asks GitHub for that (one `gh api graphql` request
per repository, however many PRs it holds), and `PullRequests` keeps the answer in the feed so a snapshot is served
from memory and never waits on GitHub. That one request also carries each PR's changed files and, for the pin bumps of
`[[repos]]`, the submodule pointer each parent merge pins and the history of each pointer in the child repository, so
`pins.link` needs no REST call unless a child merge is older than a history page. When GitHub cannot be reached for any
repository the last answer stays, marked `stale`.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from functools import partial
from itertools import groupby
from types import MappingProxyType
from typing import Protocol

from starpulse.board_feed import BoardFeed
from starpulse.ci_trail import PullHistory, parse
from starpulse.config import Repo
from starpulse.pins import GitHub, Pins, contained, link

logger = logging.getLogger(__name__)

#: Seconds between reads of GitHub.
REFRESH_S = 60.0
_GH_TIMEOUT_S = 30
_PULL = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)/?")
#: GitHub's `StatusState` for a head commit's check rollup, as the page names it; no rollup at all is `none`.
_CHECKS = {"SUCCESS": "pass", "FAILURE": "failing", "ERROR": "failing", "PENDING": "pending", "EXPECTED": "pending"}
_COMMIT_ID = re.compile(r"[0-9a-f]{40}")
_HISTORY = "history(first: 100) { pageInfo { hasNextPage } nodes { oid committedDate } }"


def _fragment(paths: Sequence[str]) -> str:
    """The `Pull` fragment; `pin<i>` reads what the merge commit has at `paths[i]`, a submodule's pinned commit."""
    pins = "".join(f" pin{i}: file(path: {json.dumps(path)}) {{ oid }}" for i, path in enumerate(paths))
    return f"""
fragment Pull on PullRequest {{
  number
  merged
  mergedAt
  mergeCommit {{ oid{pins} }}
  files(first: 100) {{ nodes {{ path }} }}
  createdAt
  mergeable
  commits(last: 100) {{ nodes {{ commit {{ oid statusCheckRollup {{ state }} checkSuites(first: 20) {{ nodes {{ status conclusion createdAt updatedAt workflowRun {{ runAttempt }} }} }} }} }} }}
  timelineItems(first: 100, itemTypes: [HEAD_REF_FORCE_PUSHED_EVENT]) {{ nodes {{ ... on HeadRefForcePushedEvent {{ createdAt afterCommit {{ oid }} }} }} }}
  reviewThreads(first: 100) {{ nodes {{ isResolved }} }}
}}
"""


class GhUnavailableError(Exception):
    """GitHub could not be read: `gh` is missing, refused, timed out or answered something unreadable."""


def read_repository(repo: str, numbers: list[int], paths: Sequence[str] = (), pointers: Sequence[str] = ()) -> dict:
    """The GraphQL `repository` node holding each of `numbers` as `p<number>`, through `gh`.

    `paths` are submodule paths each merge commit reports as `mergeCommit.pin<i>`; `pointers` are commits whose history
    page comes back as `h<i>`. A pointer that is not a full commit id is left out.
    """
    owner, name = repo.split("/")
    selections = [f"p{number}: pullRequest(number: {number}) {{ ...Pull }}" for number in numbers]
    selections += [
        f'h{i}: object(oid: "{oid}") {{ ... on Commit {{ {_HISTORY} }} }}'
        for i, oid in enumerate(pointers)
        if _COMMIT_ID.fullmatch(oid)
    ]
    query = (
        "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) "
        f"{{ {' '.join(selections)} }} }}{_fragment(paths)}"
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
    repo: str,
    wanted: list[tuple[str, int, str]],
    read: Callable[..., dict],
    out: Pulls,
    pinned: dict[str, str],
) -> dict[str, PullHistory]:
    """Add one repository's records to `out`, a PR GitHub does not return left out; returns their CI histories by URL.

    A parent repository's merges also add the pointer each pins at every `pinned` path; a pinned repository is read
    after the parents and asks for the history of every pointer they returned, adding which pointers hold its merges.
    """
    child = repo.split("/")[1] in pinned
    paths = () if child else tuple(pinned.values())
    pointers = tuple(sorted(set(out.pointers.values()))) if child else ()
    nodes = read(repo, [number for _, number, _ in wanted], paths, pointers)
    records: dict[str, dict] = {}
    pinned_at: dict[tuple[str, str, str], str] = {}
    reached: dict[tuple[str, str, str], bool] = {}
    history: dict[str, PullHistory] = {}
    try:
        for _, number, url in wanted:
            if node := nodes.get(f"p{number}"):
                rollup = node["commits"]["nodes"][-1]["commit"]["statusCheckRollup"]
                commit = node["mergeCommit"] or {}
                record = records[url] = {
                    "number": node["number"],
                    "url": url,
                    "checks": _CHECKS.get(rollup["state"], "none") if rollup else "none",
                    "merged": node["merged"],
                    "merge_sha": commit.get("oid"),
                    "merged_at": node["mergedAt"],
                    "files": [file["path"] for file in node["files"]["nodes"]],
                    "threads": sum(not thread["isResolved"] for thread in node["reviewThreads"]["nodes"]),
                    "stale": False,
                }
                history[url] = parse(url, node)
                for i, path in enumerate(paths):
                    if pin := commit.get(f"pin{i}"):
                        pinned_at[(repo, record["merge_sha"], path)] = pin["oid"]
                for i, pointer in enumerate(pointers if record["merge_sha"] else ()):
                    found = contained(record["merge_sha"], record["merged_at"], nodes.get(f"h{i}"))
                    if found is not None:
                        reached[(repo, record["merge_sha"], pointer)] = found
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise GhUnavailableError(f"unexpected GraphQL answer for {repo}: {exc!r}") from exc
    out |= records
    out.pointers |= pinned_at
    out.reaches |= reached
    return history


class Pulls(dict[str, dict]):
    """A `fetch` answer: the records read, `unread`, the URLs of repositories GitHub could not be asked about, and
    `history`, what GitHub dates of each record's CI.

    `pointers` maps (parent repo, merge commit, path) to the commit the merge pins there, and `reaches` maps (child
    repo, merge commit, pointer) to whether the pointer contains that merge; only what the batched read could settle.
    """

    unread: frozenset[str] = frozenset()
    history: Mapping[str, PullHistory] = MappingProxyType({})

    def __init__(self, *records: dict[str, dict]) -> None:
        super().__init__(*records)
        self.pointers: dict[tuple[str, str, str], str] = {}
        self.reaches: dict[tuple[str, str, str], bool] = {}


def fetch(urls: Collection[str], read: Callable[..., dict] = read_repository, repos: Sequence[Repo] = ()) -> Pulls:
    """Each URL's `{number, url, checks, merged, merge_sha, merged_at, files, threads, stale}`; a URL GitHub does not return is left out.

    `checks` is `pass`, `failing`, `pending` or `none`; `threads` counts the unresolved review threads; `files` lists
    the paths the PR changes; `merge_sha` and `merged_at` (ISO 8601 UTC) are the merge commit and merge time of a
    merged PR and `None` for an open one. Each repository is read once, repositories `repos` pins last, and the
    answer's `pointers` and `reaches` hold the pin bump facts those reads settled. A repository GitHub cannot read is
    logged, left out and named in `unread` so the others still answer; only when every repository fails does the read
    raise `GhUnavailableError`, for `PullRequests.refresh` to keep its last answer.
    """
    pinned = {repo.name: repo.path for repo in repos}
    pulls = sorted((m[1], int(m[2]), url) for url in urls if (m := _PULL.fullmatch(url)))
    out = Pulls()
    history: dict[str, PullHistory] = {}
    unread: set[str] = set()
    failures: list[GhUnavailableError] = []
    groups = [(repo, list(group)) for repo, group in groupby(pulls, key=lambda pull: pull[0])]
    # Parents first: the pointers their merges pin go in the query of the repository pinned.
    groups.sort(key=lambda group: group[0].split("/")[1] in pinned)
    for repo, wanted in groups:
        try:
            history |= _read_pulls(repo, wanted, read, out, pinned)
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
        fetch: Callable[[Collection[str]], Pulls] | None = None,
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
            fresh = (self._fetch or partial(fetch, repos=self._repos))(urls) if urls else Pulls()
            if isinstance(self._pins, GitHub):
                self._pins.learn(fresh.pointers, fresh.reaches)
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
