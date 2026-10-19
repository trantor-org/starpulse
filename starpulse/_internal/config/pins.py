"""Pin bumps: which parent merge applies a merge in a repository the parent pins as a submodule.

A `[[repos]]` entry says a repository's merges reach live state through the parent's pin bump: the parent merge whose
submodule pointer first contains the child's merge commit. `link` finds that merge; the pointer and containment
reads are GitHub calls, so `GitHub` memoizes them (a commit's pointer and a pair of commits never change) and the
caller runs `link` on the timer that projects pull requests, never under the feed's lock. The answers are saved with
the Board (`answers`), and `GitHub` takes them back before its first read (`saved`), whoever makes it, so a restart
asks GitHub for none of them again.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib import metadata
from typing import Protocol

from starpulse._internal.config.config import Repo

__all__ = ["GitHub", "LiveBuild", "Pins", "build_commit", "contained", "link", "running_commit"]

logger = logging.getLogger(__name__)

_PULL = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/\d+/?")
_GH_TIMEOUT_S = 30
#: Seconds a read of a default branch's head commit is reused; the branch moves, so it is never saved.
_HEAD_TTL_S = 60.0
_RETRY_WAIT_S = 300.0
#: `compare` statuses meaning the pointer's commit is, or descends from, the compared merge.
_CONTAINS = {"ahead", "identical"}
_COMMIT_ID = re.compile(r"[0-9a-f]{40}")
#: What `_api` answers for a path GitHub has none of; no `jq` output holds a NUL, so it is never a pointer.
_MISSING = "\0missing"


@dataclass(frozen=True)
class LiveBuild:
    """The repository the running build comes from and a read of the commit that build is at."""

    repo: str
    commit: Callable[[], str | None]


_BUILD_COMMIT = re.compile(r"\+g([0-9a-f]{7,40})(?:\.|$)")


def build_commit(version: str) -> str | None:
    """The commit a build was made at: the `g<sha>` in its PEP 440 local version (`0.4.0.post3+g1a2b3c4`), or None."""
    found = _BUILD_COMMIT.search(version)
    return found[1] if found else None


@cache
def running_commit() -> str | None:
    """The commit this process's build is at, read once: a reload that does not restart it keeps the code it imported."""
    return build_commit(metadata.version("starpulse"))


class Pins(Protocol):
    """The two reads `link` needs from the parent and the child repositories."""

    def pointer(self, repo: str, sha: str, path: str) -> str | None: ...

    def reaches(self, repo: str, sha: str, pointer: str) -> bool: ...

    def head(self, repo: str) -> str | None: ...


def link(
    pulls: Mapping[str, Mapping],
    repos: Sequence[Repo],
    pointer: Callable[[str, str, str], str | None],
    reaches: Callable[[str, str, str], bool],
) -> dict[str, dict]:
    """`pulls` (records by URL) with `applied_by` on each merged pull request of a declared repository.

    `applied_by` is the merge commit of the earliest later merge in any other repository whose submodule pointer at
    the declared path contains the child's merge commit, or None while no such merge exists. `pointer(repo, sha, path)`
    is the commit the parent (`owner/name`) pins at `path` as of `sha`, None when unreadable; `reaches(repo, sha,
    pointer)` says whether commit `pointer` of the child (`owner/name`) contains `sha`.
    """
    pinned = {repo.name: repo.path for repo in repos}
    merged = sorted(
        (
            (record["merged_at"], found, record)
            for record in pulls.values()
            if record.get("merged")
            and record.get("merge_sha")
            and record.get("merged_at")
            and (found := _PULL.fullmatch(record["url"]))
        ),
        key=lambda item: item[0],
    )
    parents = [(at, found, record) for at, found, record in merged if found[2] not in pinned]
    out = {url: dict(record) for url, record in pulls.items()}
    for at, found, child in merged:
        if (path := pinned.get(found[2])) is None:
            continue
        applied = None
        for later, parent_found, parent in parents:
            if later < at:
                continue
            at_parent = pointer(f"{parent_found[1]}/{parent_found[2]}", parent["merge_sha"], path)
            if at_parent and reaches(f"{found[1]}/{found[2]}", child["merge_sha"], at_parent):
                applied = parent["merge_sha"]
                break
        out[child["url"]]["applied_by"] = applied
    return out


def contained(sha: str, merged_at: str, history: Mapping | None) -> bool | None:
    """Whether a pointer's commit contains `sha`, a merge made at `merged_at`, as its GraphQL `history` page answers it.

    `history` is the pointer `Commit` node, `{history: {pageInfo: {hasNextPage}, nodes: [{oid, committedDate}]}}`,
    newest first, or None when GitHub could not read the pointer. The merge is in the page or not; a page that
    holds the whole history, or reaches back past the merge's time, rules it out. None means the merge is older than
    a full page and only a `compare` can say.
    """
    page = (history or {}).get("history")
    if not page or not page["nodes"]:
        return None
    nodes = page["nodes"]
    if any(node["oid"] == sha for node in nodes):
        return True
    if not page["pageInfo"]["hasNextPage"] or merged_at > min(node["committedDate"] for node in nodes):
        return False
    return None


class GitHub:
    """The pointer and containment reads `link` needs, through `gh`; an answer is kept, an unreadable one is not.
    A path GitHub answers 404 for is an answer, None: a commit that pins nothing there never will."""

    def __init__(self, saved: Callable[[], Mapping[str, list[list]]] = dict) -> None:
        """`saved` returns the answers the Board last saved; it is called once, when the first read needs them."""
        self._pointers: dict[tuple[str, str, str], str | None] = {}
        self._reaches: dict[tuple[str, str, str], bool] = {}
        self._saved: Callable[[], Mapping[str, list[list]]] | None = saved
        self._heads: dict[str, tuple[float, str | None]] = {}
        self._unreadable: dict[tuple[str, ...], float] = {}

    def _retry(self, key: tuple[str, ...]) -> bool:
        """Whether `key` may be asked: it has not failed within `_RETRY_WAIT_S`. A failing read is not re-asked every pass."""
        failed_at = self._unreadable.get(key)
        return failed_at is None or time.monotonic() - failed_at >= _RETRY_WAIT_S

    def _restored(self) -> None:
        if self._saved is not None:
            saved, self._saved = self._saved, None
            self.restore(saved())

    def pointer(self, repo: str, sha: str, path: str) -> str | None:
        self._restored()
        key = (repo, sha, path)
        if key not in self._pointers and self._retry(("pointer", *key)):
            found = _api(f"repos/{repo}/contents/{path}?ref={sha}", ".sha", missing=_MISSING)
            if found:
                self._pointers[key] = None if found == _MISSING else found
            else:
                self._unreadable[("pointer", *key)] = time.monotonic()
        return self._pointers.get(key)

    def reaches(self, repo: str, sha: str, pointer: str) -> bool:
        self._restored()
        key = (repo, sha, pointer)
        if key not in self._reaches and self._retry(("reaches", *key)):
            status = _api(f"repos/{repo}/compare/{sha}...{pointer}", ".status")
            if status:
                self._reaches[key] = status in _CONTAINS
            else:
                self._unreadable[("reaches", *key)] = time.monotonic()
        return self._reaches.get(key, False)

    def head(self, repo: str) -> str | None:
        """The commit `repo`'s default branch is at, read again once `_HEAD_TTL_S` has passed since the last read."""
        now = time.monotonic()
        read_at, sha = self._heads.get(repo, (-_HEAD_TTL_S, None))
        if now - read_at >= _HEAD_TTL_S:
            sha = _api(f"repos/{repo}/commits/HEAD", ".sha")
            self._heads[repo] = (now, sha)
        return sha

    def answers(self) -> dict[str, list[list]]:
        """Every answer kept, as JSON a saved Board can hold; `restore` takes it back."""
        return {
            "pointers": [[*key, found] for key, found in self._pointers.items()],
            "reaches": [[*key, contained] for key, contained in self._reaches.items()],
        }

    def restore(self, answers: Mapping[str, list[list]]) -> None:
        """Keep the answers `answers` saved, so those reads are never asked again; an unreadable entry, or a pointer
        that is not a commit id (an error body an older reader kept), is skipped."""
        for repo, sha, path, found in (row for row in answers.get("pointers", []) if len(row) == 4):
            if found is None or _COMMIT_ID.fullmatch(found):
                self._pointers.setdefault((repo, sha, path), found)
        for repo, sha, pointer, contained in (row for row in answers.get("reaches", []) if len(row) == 4):
            if _COMMIT_ID.fullmatch(pointer):
                self._reaches.setdefault((repo, sha, pointer), bool(contained))


def _api(endpoint: str, jq: str, missing: str | None = None) -> str | None:
    """`jq` of the endpoint's answer, None when `gh` fails (it prints the error body to stdout) or prints nothing;
    `missing` when the failure is GitHub's 404, which is an answer and not a read to try again."""
    try:
        result = subprocess.run(
            ["gh", "api", endpoint, "--jq", jq], capture_output=True, text=True, timeout=_GH_TIMEOUT_S
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("pin bumps: %s", exc)
        return None
    if result.returncode == 0:
        return result.stdout.strip() or None
    return missing if _not_found(result.stdout) else None


def _not_found(body: str) -> bool:
    """Whether `body` is GitHub's 404 error answer."""
    try:
        answer = json.loads(body)
    except ValueError:
        return False
    return isinstance(answer, dict) and answer.get("status") == "404"
