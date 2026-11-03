"""Pin bumps: which parent merge applies a merge in a repository the parent pins as a submodule.

A `[[repos]]` entry says a repository's merges reach live state through the parent's pin bump: the parent merge whose
submodule pointer first contains the child's merge commit. `link` finds that merge; the pointer and containment
reads are GitHub calls, so `GitHub` memoizes them (a commit's pointer and a pair of commits never change) and the
caller runs `link` on the timer that projects pull requests, never under the feed's lock. The answers are saved with
the Board (`answers`), and `GitHub` takes them back before its first read (`saved`), whoever makes it, so a restart
asks GitHub for none of them again.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib import metadata
from typing import Protocol

__all__ = ["LiveBuild", "Pins", "Repo", "build_commit", "contained", "link", "running_commit"]

@dataclass(frozen=True)
class Repo:
    """A repository whose merges reach live state through the parent's pin bump (`[[repos]]`)."""

    name: str
    """The repository's name as its pull request links spell it (`trantor-org/<name>`)."""
    path: str
    """Where the parent repository holds it as a submodule."""
    applied_by: str
    """How its merges are applied; only `pin-bump`."""


_PULL = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/\d+/?")


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

    def failing(self) -> list[str]: ...


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
