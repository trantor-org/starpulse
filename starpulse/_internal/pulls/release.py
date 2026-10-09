"""Release a Waiting task to Ready when every task it depends on has settled.

A dependency settles when its task is Done (completed, or in the `done` lane). With `[release] settle = "pin-bump"` a
dependency that cites a pull request in a `[[repos]]` repository settles only once the parent's pin bump has merged:
the merge in the PR store whose submodule pointer at the repository's path contains the dependency's merge commit
(`pins.link`). A pull request the store does not hold or holds open holds the dependent, the fail-closed direction; a
closed, unmerged one never reaches the pin and is ignored. A task that Start Criteria also gate is left to them.
The bump is looked for among the merged pull requests of the child's owner in repositories that are not pinned, so
one a task never cited still settles the dependency; one older than the store's records is not found and holds it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from starpulse._internal.board.seam import TaskEditor
from starpulse._internal.config.config import Repo
from starpulse._internal.config.pins import GitHub, Pins, link
from starpulse._internal.feed import criteria
from starpulse._internal.feed.board_feed import WAITING, BoardFeed
from starpulse._internal.pulls.pull_requests import PULL_URL
from starpulse._internal.pulls.pulls import PullStore

logger = logging.getLogger(__name__)

#: Seconds between passes over the Waiting tasks.
RELEASE_S = 30.0
READY = "ready"
COMMENT = "Every dependency has settled; StarPulse moved this task to Ready."


class Releaser:
    """Moves each Waiting task whose dependencies have settled to Ready, through the board's task editor."""

    def __init__(
        self,
        feed: BoardFeed,
        store: PullStore,
        edit: TaskEditor,
        repos: Sequence[Repo] = (),
        settle: str | None = None,
        pins: Pins | None = None,
    ) -> None:
        self._feed = feed
        self._store = store
        self._edit = edit
        self._pinned = {repo.name: repo.path for repo in repos} if settle == "pin-bump" else {}
        self._repos = repos
        self._pins = pins or GitHub()
        #: Tasks released that the feed still shows Waiting, so the board's next read is not written over again.
        self._sent: set[str] = set()

    def release(self) -> list[str]:
        """Move every releasable Waiting task to Ready once; the ids moved. A refused or failed write is logged and
        tried again on the next pass."""
        waiting = [
            agent
            for agent in sorted(self._feed.open_tasks(), key=lambda agent: agent["id"])
            if agent["state"] == WAITING and agent["dependencies"]
        ]
        self._sent &= {agent["id"] for agent in waiting}
        moved: list[str] = []
        for agent in waiting:
            name = agent["id"]
            if name in self._sent or not agent["workable"] or criteria.authored(agent["description"]):
                continue
            if self._unapplied(agent):
                continue
            try:
                written = self._edit(name, {"status": READY}, COMMENT)
            except Exception:  # one task's write must not end the pass
                logger.exception("release: cannot move %s to Ready", name)
                continue
            if written.ok:
                self._sent.add(name)
                moved.append(name)
            else:
                logger.warning("release: %s was not moved to Ready: %s", name, written.output)
        return moved

    def _unapplied(self, agent: dict[str, Any]) -> bool:
        """Whether a dependency's merged change in a pinned repository is not in the parent's pin yet."""
        merges: list[dict] | None = None  # read once, and only for a task that needs the evidence
        for dependency in agent["dependencies"]:
            for url in self._feed.cited(dependency):
                found = PULL_URL.fullmatch(url)
                if found is None or (path := self._pinned.get(found[1].partition("/")[2])) is None:
                    continue
                records = self._store.find(repo=found[1], number=int(found[2]))
                if not records:
                    return True
                child = records[0]
                if child["state"] == "CLOSED":
                    continue
                if child["state"] != "MERGED" or not child["mergeSha"] or not child["mergedAt"]:
                    return True
                if merges is None:
                    merges = self._merges()
                owner = found[1].partition("/")[0]
                bumps = [
                    merge
                    for merge in merges
                    if merge["repo"].startswith(f"{owner}/") and path in merge["detail"]["files"]
                ]
                projected = {record["url"]: record for record in map(_projected, [child, *bumps])}
                if not link(projected, self._repos, self._pins.pointer, self._pins.reaches)[url].get("applied_by"):
                    return True
        return False

    def _merges(self) -> list[dict]:
        """Every merged pull request the store holds with its detail, in the repositories that are not pinned."""
        return [
            record
            for repo in self._store.repos()
            if repo.partition("/")[2] not in self._pinned
            for record in self._store.find(repo=repo, state="MERGED", detailed=True)
            if record["detail"]
        ]


def _projected(record: dict[str, Any]) -> dict[str, Any]:
    """A store record as `pins.link` reads a pull request."""
    return {
        "url": f"https://github.com/{record['repo']}/pull/{record['number']}",
        "merged": record["state"] == "MERGED",
        "merge_sha": record["mergeSha"],
        "merged_at": record["mergedAt"],
    }
