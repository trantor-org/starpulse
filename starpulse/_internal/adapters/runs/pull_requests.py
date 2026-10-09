"""Each open task's pull requests, read from GitHub on a timer and carried in the snapshot.

The Board's tasks cite their pull requests as links; nothing on the projection says whether a PR's checks pass,
whether it merged or how many review threads are open. `fetch` asks GitHub for that (one `gh api graphql` request
per repository, however many PRs it holds), and `PullRequests` keeps the answer in the feed so a snapshot is served
from memory and never waits on GitHub. That one request also carries each PR's changed files and, for the pin bumps of
`[[repos]]`, the submodule pointer each parent merge pins and the history of each pointer in the child repository, so
`pins.link` needs no REST call unless a child merge is older than a history page. A PR seen merged or closed cannot
change, so its saved record is carried and later reads leave it out of the query: the check-suite trail is read only for
PRs not yet merged or closed. Each query's `rateLimit` cost is logged. When GitHub cannot be reached for any
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

from starpulse._internal.projections.board_feed import BoardFeed
from starpulse._internal.projections.ci_trail import PullHistory, parse
from starpulse._internal.settings.config import Repo
from starpulse._internal.settings.pins import GitHub, Pins, contained, link

logger = logging.getLogger(__name__)

#: Seconds between reads of GitHub.
REFRESH_S = 60.0
_GH_TIMEOUT_S = 30
PULL_URL = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)/?")
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
  closed
  mergedAt
  mergeCommit {{ oid{pins} }}
  files(first: 100) {{ nodes {{ path }} }}
  createdAt
  mergeable
  headRef {{ compare(headRef: "main") {{ aheadBy }} }}
  commits(last: 100) {{ nodes {{ commit {{ oid statusCheckRollup {{ state }} checkSuites(first: 20) {{ nodes {{ status conclusion createdAt updatedAt workflowRun {{ runAttempt }} }} }} }} }} }}
  timelineItems(first: 100, itemTypes: [HEAD_REF_FORCE_PUSHED_EVENT]) {{ nodes {{ ... on HeadRefForcePushedEvent {{ createdAt afterCommit {{ oid }} }} }} }}
  reviewThreads(first: 100) {{ nodes {{ isResolved }} }}
}}
"""


class GhUnavailableError(Exception):
    """GitHub could not be read: `gh` is missing, refused, timed out or answered something unreadable."""


def query_github(repo: str, query: str) -> dict:
    """The `repository` node `query` (one `gh api graphql` request about `repo`, which names `$owner` and `$name`) returns.

    The request's `rateLimit` cost is logged. Raises `GhUnavailableError` when `gh` fails or answers nothing readable.
    """
    owner, name = repo.split("/")
    command = ["gh", "api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=_GH_TIMEOUT_S)
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


def read_repository(repo: str, numbers: list[int], paths: Sequence[str] = (), pointers: Sequence[str] = ()) -> dict:
    """The GraphQL `repository` node holding each of `numbers` as `p<number>`, through `gh`.

    `paths` are submodule paths each merge commit reports as `mergeCommit.pin<i>`; `pointers` are commits whose history
    page comes back as `h<i>`. A pointer that is not a full commit id is left out.
    """
    selections = [f"p{number}: pullRequest(number: {number}) {{ ...Pull }}" for number in numbers]
    selections += [
        f'h{i}: object(oid: "{oid}") {{ ... on Commit {{ {_HISTORY} }} }}'
        for i, oid in enumerate(pointers)
        if _COMMIT_ID.fullmatch(oid)
    ]
    return query_github(
        repo,
        "query($owner: String!, $name: String!) { rateLimit { cost remaining resetAt } "
        f"repository(owner: $owner, name: $name) {{ {' '.join(selections)} }} }}{_fragment(paths) if numbers else ''}",
    )


def _reached(repo: str, record: dict, pointers: Sequence[str], nodes: dict) -> dict[tuple[str, str, str], bool]:
    """Which `pointers` hold `record`'s merge commit, as far as the pointers' history pages (`h<i>` in `nodes`) say."""
    reached = {}
    for i, pointer in enumerate(pointers if record["merge_sha"] else ()):
        found = contained(record["merge_sha"], record["merged_at"], nodes.get(f"h{i}"))
        if found is not None:
            reached[(repo, record["merge_sha"], pointer)] = found
    return reached


def _read_pulls(
    repo: str,
    wanted: list[tuple[str, int, str]],
    carried: list[dict],
    read: Callable[..., dict],
    out: Pulls,
    pinned: dict[str, str],
) -> dict[str, PullHistory]:
    """Add one repository's records to `out`, a PR GitHub does not return left out; returns their CI histories by URL.

    A parent repository's merges also add the pointer each pins at every `pinned` path; a pinned repository is read
    after the parents and asks for the history of every pointer they returned, adding which pointers hold its merges.
    `carried` are records already in `out` that are not asked for; those of a pinned repository's merges that no parent
    merge applies yet are still checked against the pointers returned, so a repository holding nothing else to read
    is queried only for that.
    """
    child = repo.split("/")[1] in pinned
    paths = () if child else tuple(pinned.values())
    pointers = tuple(sorted({oid for oid in out.pointers.values() if oid})) if child else ()
    waiting = [record for record in carried if child and record["merged"] and not record.get("applied_by")]
    if not wanted and not (pointers and waiting):
        return {}
    nodes = read(repo, [number for _, number, _ in wanted], paths, pointers)
    records: dict[str, dict] = {}
    pinned_at: dict[tuple[str, str, str], str | None] = {}
    reached: dict[tuple[str, str, str], bool] = {}
    history: dict[str, PullHistory] = {}
    closed: set[str] = set()
    try:
        for record in waiting:
            reached |= _reached(repo, record, pointers, nodes)
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
                    "behind_main": ((node["headRef"] or {}).get("compare") or {}).get("aheadBy"),
                    "stale": False,
                }
                history[url] = parse(url, node)
                for i, path in enumerate(paths):  # a null `pin<i>` is a settled answer: nothing is pinned at the path
                    if f"pin{i}" in commit:
                        pinned_at[(repo, record["merge_sha"], path)] = (commit[f"pin{i}"] or {}).get("oid")
                reached |= _reached(repo, record, pointers, nodes)
                if node["closed"] and not node["merged"]:
                    closed.add(url)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise GhUnavailableError(f"unexpected GraphQL answer for {repo}: {exc!r}") from exc
    out |= records
    out.closed |= closed
    out.pointers |= pinned_at
    out.reaches |= reached
    return history


class Pulls(dict[str, dict]):
    """A `fetch` answer: the records read, `unread`, the URLs of repositories GitHub could not be asked about, and
    `closed`, the URLs read as closed without merging, and `history`, what GitHub dates of each record's CI.

    `pointers` maps (parent repo, merge commit, path) to the commit the merge pins there, None when it has nothing at
    that path, and `reaches` maps (child repo, merge commit, pointer) to whether the pointer contains that merge; only
    what the batched read could settle.
    """

    unread: frozenset[str] = frozenset()
    closed: set[str]
    history: Mapping[str, PullHistory] = MappingProxyType({})

    def __init__(self, *records: dict[str, dict]) -> None:
        super().__init__(*records)
        self.closed = set()
        self.pointers: dict[tuple[str, str, str], str | None] = {}
        self.reaches: dict[tuple[str, str, str], bool] = {}


def fetch(
    urls: Collection[str],
    read: Callable[..., dict] = read_repository,
    repos: Sequence[Repo] = (),
    final: Mapping[str, dict] = MappingProxyType({}),
) -> Pulls:
    """Each URL's `{number, url, checks, merged, merge_sha, merged_at, files, threads, behind_main, stale}`; a URL GitHub does not return is left out.

    `checks` is `pass`, `failing`, `pending` or `none`; `threads` counts the unresolved review threads; `behind_main` is how many commits `main` holds that the PR's head
    lacks, `None` once its head branch is gone; `files` lists
    the paths the PR changes; `merge_sha` and `merged_at` (ISO 8601 UTC) are the merge commit and merge time of a
    merged PR and `None` for an open one. Each repository is read once, repositories `repos` pins last, and the
    answer's `pointers` and `reaches` hold the pin bump facts those reads settled. A repository GitHub cannot read is
    logged, left out and named in `unread` so the others still answer; only when every repository fails does the read
    raise `GhUnavailableError`, for `PullRequests.refresh` to keep its last answer. A URL with a record in `final`, a
    PR that merged or closed, is not asked for: its record comes back as saved, never `stale`.
    """
    pinned = {repo.name: repo.path for repo in repos}
    pulls = sorted((m[1], int(m[2]), url) for url in urls if (m := PULL_URL.fullmatch(url)))
    out = Pulls({url: {**final[url], "stale": False} for _, _, url in pulls if url in final})
    history: dict[str, PullHistory] = {}
    unread: set[str] = set()
    failures: list[GhUnavailableError] = []
    groups = [(repo, list(group)) for repo, group in groupby(pulls, key=lambda pull: pull[0])]
    # Parents first: the pointers their merges pin go in the query of the repository pinned.
    groups.sort(key=lambda group: group[0].split("/")[1] in pinned)
    for repo, group in groups:
        wanted = [pull for pull in group if pull[2] not in final]
        try:
            history |= _read_pulls(repo, wanted, [out[url] for _, _, url in group if url in final], read, out, pinned)
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
        read: Callable[..., dict] = read_repository,
    ) -> None:
        self._feed = feed
        self._fetch = fetch
        self._repos = repos
        self._pins = pins or GitHub()
        self._trail = trail
        self._read = read
        self._last: dict[str, dict] = {}
        #: URLs read as closed without merging; a merged PR is final by its record, a closed one by being named here.
        self._closed: set[str] = set()

    def _final(self) -> dict[str, dict]:
        """The saved records of PRs that cannot change, which the next read leaves out of the query."""
        return {url: pull for url, pull in self._last.items() if pull["merged"] or url in self._closed}

    def refresh(self) -> None:
        """Read every open task's PRs once; a PR GitHub could not be asked about keeps its last record, marked `stale`."""
        wanted = self._feed.pull_requests()
        urls = list(dict.fromkeys(url for prs in wanted.values() for url in prs))
        try:
            fresh = (
                (self._fetch or partial(fetch, read=self._read, repos=self._repos, final=self._final()))(urls)
                if urls
                else Pulls()
            )
            if isinstance(self._pins, GitHub):
                self._pins.learn(fresh.pointers, fresh.reaches)
            kept = {url: {**self._last[url], "stale": True} for url in fresh.unread if url in self._last}
            self._last = {**fresh, **kept}
            self._closed = {url for url in self._closed | fresh.closed if url in self._last}
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
        return {"records": self._last, "pins": pins, "closed": sorted(self._closed)}

    def restore(self) -> None:
        """Start from the answers the feed resumed with (`BoardFeed.pull_answers`), so a restart reads GitHub warm."""
        saved = self._feed.pull_answers()
        self._last = {**saved.get("records", {}), **self._last}
        self._closed |= set(saved.get("closed", []))
        if isinstance(self._pins, GitHub):
            self._pins.restore(saved.get("pins", {}))

    def run_forever(self, interval_s: float = REFRESH_S) -> None:  # pragma: no mutate block — timer loop
        """Refresh once the Board replay is done, so the first read sees every task, then every `interval_s`."""
        self._feed.wait_replayed()
        self.restore()
        while True:
            self.refresh()
            time.sleep(interval_s)
