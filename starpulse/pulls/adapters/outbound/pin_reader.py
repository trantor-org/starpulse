"""The pins GitHub reader: the pointer and containment reads `link` needs, through the `Transport` GitHub calls go by."""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable, Mapping

from starpulse.github.adapters.outbound.rest import Transport, connect

#: Seconds a read of a default branch's head commit is reused; the branch moves, so it is never saved.
_HEAD_TTL_S = 60.0
_RETRY_WAIT_S = 300.0
#: `compare` statuses meaning the pointer's commit is, or descends from, the compared merge.
_CONTAINS = {"ahead", "identical"}
_COMMIT_ID = re.compile(r"[0-9a-f]{40}")
#: What `_read` answers for a path GitHub has none of; a field value never holds a NUL, so it is never a pointer.
_MISSING = "\0missing"
logger = logging.getLogger(__name__)


class GitHub:
    """The pointer and containment reads `link` needs, through a `Transport`; an answer is kept, an unreadable one is not.
    A path GitHub answers 404 for is an answer, None: a commit that pins nothing there never will."""

    def __init__(
        self, saved: Callable[[], Mapping[str, list[list]]] = dict, transport: Transport | None = None
    ) -> None:
        """`saved` returns the answers the Board last saved; it is called once, when the first read needs them.
        `transport` defaults to one signed in with `GITHUB_TOKEN` or `GH_TOKEN`."""
        self._transport = transport or connect(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
        self._pointers: dict[tuple[str, str, str], str | None] = {}
        self._reaches: dict[tuple[str, str, str], bool] = {}
        self._saved: Callable[[], Mapping[str, list[list]]] | None = saved
        self._heads: dict[str, tuple[float, str | None]] = {}
        self._unreadable: dict[tuple[str, ...], float] = {}
        self._failing: dict[str, None] = {}

    def failing(self) -> list[str]:
        """The endpoints whose latest read failed, oldest first: a False or None answer that is a failed call."""
        return list(self._failing)

    def _read(self, endpoint: str, field: str, missing: str | None = None) -> str | None:
        """`field` of the endpoint's answer, None when the call fails; `missing` when GitHub answers 404, which is an
        answer and not a read to try again. A failed call is named by `failing` until a later read of it answers."""
        try:
            status, body = self._transport("GET", endpoint, None)
        except OSError as exc:
            logger.warning("pin bumps: %s", exc)
            status, body = 0, {}
        found = body.get(field) if status == 200 else missing if status == 404 else None
        if found:
            self._failing.pop(endpoint, None)
        else:
            self._failing[endpoint] = None
        return found

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
            found = self._read(f"repos/{repo}/contents/{path}?ref={sha}", "sha", missing=_MISSING)
            if found:
                self._pointers[key] = None if found == _MISSING else found
            else:
                self._unreadable[("pointer", *key)] = time.monotonic()
        return self._pointers.get(key)

    def reaches(self, repo: str, sha: str, pointer: str) -> bool:
        self._restored()
        key = (repo, sha, pointer)
        if key not in self._reaches and self._retry(("reaches", *key)):
            status = self._read(f"repos/{repo}/compare/{sha}...{pointer}", "status")
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
            sha = self._read(f"repos/{repo}/commits/HEAD", "sha")
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
