"""The commit a repository's default branch passed its required checks at."""

import time
from collections.abc import Callable

from starpulse.github.model.checks import rollup
from starpulse.github.ports.events import Reader

__all__ = ["MainGreen"]

#: Seconds a head that has not passed keeps its verdict before its checks are read again; a pass is kept.
_PENDING_TTL_S = 60.0


class MainGreen:
    """Calls to the SHA of `repository`'s default-branch head when every check its rules require passed on it, else None.

    `head` reads the head SHA. A pass is kept for that head; any other verdict is read again after `_PENDING_TTL_S`.
    """

    def __init__(
        self, repository: str, head: Callable[[str], str | None], reader: Reader, branch: str = "main"
    ) -> None:
        self._repository, self._head, self._reader, self._branch = repository, head, reader, branch
        self._read: tuple[str, bool, float] | None = None

    def __call__(self) -> str | None:
        try:
            return self._green()
        except OSError:
            return None

    def forget(self) -> None:
        """Drop the kept verdict: a finished checks run on main changed what the next call reads."""
        self._read = None

    def _green(self) -> str | None:
        sha = self._head(self._repository)
        if sha is None:
            return None
        now = time.monotonic()
        if self._read is None or self._read[0] != sha or not (self._read[1] or now - self._read[2] < _PENDING_TTL_S):
            required = self._reader.required(self._repository, self._branch)
            passed = bool(required) and rollup(required, self._reader.results(self._repository, sha)) == "passed"
            self._read = (sha, passed, now)
        return sha if self._read[1] else None
