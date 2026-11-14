"""The gate on a Waiting task's release: every task it depends on has merged.

A dependency is merged when its task is Done (completed, or in the `done` lane). With the `[release]` pin-bump rule a
dependency that cites a pull request in a `[[repos]]` repository is merged only once the parent's pin bump has merged:
the merge in the PR store whose submodule pointer at the repository's path contains the dependency's merge commit
(`pins.link`). A pull request the store does not hold or holds open holds the dependent, the fail-closed direction; a
closed, unmerged one never reaches the pin and is ignored. A task that Start Criteria also gate is left to them.
The bump is looked for among the merged pull requests of the child's owner in repositories that are not pinned, so
one a task never cited still counts as merged; one older than the store's records is not found and holds it.
A pin pushed to the parent's default branch with no pull request counts too: the branch head's pointer is read.
While a GitHub read of those fails, the hold names the failed call, never "no bump pins it".
With the `[release]` release rule a dependency that cites a merged pull request in the `repo` it names is merged only
once the running build's commit contains the merge commit (`PinGate._built`); a build with no commit holds it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from starpulse.board.model.board_feed import BoardFeed
from starpulse.pulls.adapters.outbound.pin_reader import GitHub
from starpulse.pulls.adapters.outbound.pull_requests import PULL_URL, delivers
from starpulse.pulls.model.pins import LiveBuild, Pins, Repo, link

if TYPE_CHECKING:  # annotation only: the pull store opens the database stack
    from starpulse.pulls.adapters.outbound.pulls import PullStore

class PinGate:
    """Whether a dependency's merge has not reached live state: the parent's pin under `[release]` pin-bump, or the
    running build under `release`."""

    def __init__(
        self,
        feed: BoardFeed,
        store: PullStore,
        repos: Sequence[Repo] = (),
        pin_rule: str | None = None,
        pins: Pins | None = None,
        live: LiveBuild | None = None,
    ) -> None:
        self._feed = feed
        self._store = store
        self._live = live
        self._pinned = {repo.name: repo.path for repo in repos} if pin_rule == "pin-bump" else {}
        self._repos = repos
        self._pins = pins or GitHub(lambda: feed.pull_answers().get("pins", {}))

    def waiting_on(self, agent: dict[str, Any]) -> str | None:
        """Why a dependency's merged change is not in the parent's pin, or the running build, yet; None when it is.
        Only a pull request that can be the dependency's own delivery counts: one naming another task is a reference."""
        merges: list[dict] | None = None  # read once, and only for a task that needs the evidence
        for dependency in agent["dependencies"]:
            for url in self._feed.cited(dependency):
                found = PULL_URL.fullmatch(url)
                if found is None:
                    continue
                name = found[1].partition("/")[2]
                path = self._pinned.get(name)
                if path is None and (self._live is None or self._live.repo != name):
                    continue
                if not delivers(self._store, url, dependency):
                    continue
                records = self._store.find(repo=found[1], number=int(found[2]))
                if not records:
                    return f"{url} is not in the pull store"
                child = records[0]
                if child["state"] == "CLOSED":
                    continue
                if child["state"] != "MERGED" or not child["mergeSha"] or not child["mergedAt"]:
                    return f"{url} is not merged"
                if path is None:
                    if not self._built(found[1], child["mergeSha"]):
                        return f"the running build does not contain {url}"
                    continue
                if merges is None:
                    merges = self._merges()
                owner = found[1].partition("/")[0]
                bumps = [
                    merge
                    for merge in merges
                    if merge["repo"].startswith(f"{owner}/") and path in (merge["detail"]["files"] or ())
                ]
                projected = {record["url"]: record for record in map(_projected, [child, *bumps])}
                applied = link(projected, self._repos, self._pins.pointer, self._pins.reaches)[url].get("applied_by")
                if not applied and not self._at_head(found[1], child["mergeSha"], path):
                    if failing := self._pins.failing():
                        return f"{url} is merged; a GitHub read failed, so a pin at {path} is unknown: {', '.join(failing)}"
                    return f"{url} is merged but no merged bump pins it at {path} yet"
        return None

    def _built(self, repo: str, sha: str) -> bool:
        """Whether the running build contains `sha`: a build with no commit contains nothing."""
        assert self._live is not None
        commit = self._live.commit()
        return commit is not None and self._pins.reaches(repo, sha, commit)

    def _at_head(self, child: str, sha: str, path: str) -> bool:
        """Whether a parent's default branch pins `sha` of `child` at `path`: a pin pushed there with no bump PR."""
        owner = child.partition("/")[0]
        for repo in self._store.repos():
            if not repo.startswith(f"{owner}/") or repo.partition("/")[2] in self._pinned:
                continue
            tip = self._pins.head(repo)
            at_tip = self._pins.pointer(repo, tip, path) if tip else None
            if at_tip and self._pins.reaches(child, sha, at_tip):
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
