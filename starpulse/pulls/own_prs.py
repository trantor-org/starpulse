"""A task's own delivery among the pull requests it cites."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from starpulse.pulls.pull_requests import PULL_URL

if TYPE_CHECKING:  # annotation only: the pull store opens the database stack
    from starpulse.pulls.pulls import PullStore

__all__ = ["merged", "own_prs", "pull_record"]

_TASK_ID = re.compile(r"task-\d+")


def pull_record(store: PullStore, url: str) -> dict[str, Any] | None:
    """The store's record of the pull request at `url`, None when it holds none."""
    found = PULL_URL.fullmatch(url)
    records = store.find(repo=found[1], number=int(found[2])) if found else []
    return records[0] if records else None


def own_prs(store: PullStore, agent: dict[str, Any]) -> list[str]:
    """The cited pull requests that are not another task's delivery: one whose branch or title names tasks and not
    this one is a reference, never proof of this task's work."""
    own = []
    for url in agent["prs"]:
        found = pull_record(store, url)
        text = f"{found.get('headRefName', '')} {found.get('title', '')}" if found else ""
        named = set(_TASK_ID.findall(text.lower()))
        if not named or agent["id"].lower() in named:
            own.append(url)
    return own


def merged(store: PullStore, agent: dict[str, Any]) -> bool:
    """Whether one of the task's own pull requests has merged."""
    for url in own_prs(store, agent):
        found = pull_record(store, url)
        if found and found["state"] == "MERGED" and found["mergedAt"]:
            return True
    return False
