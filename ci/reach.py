"""Which of a pull request's checks a change reaches: the changed paths on stdin, one `check=true|false` line per check.

`ci.yml` reads these lines to skip a job whose result the change cannot alter. A skipped job counts as passed for a required
check, so a docs edit does not wait on the page build. The schedule and a dispatch run every job without asking.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from fnmatch import fnmatch

#: A change to any of these runs every check: a dependency pin or the CI config can change what each one does.
FULL = ("uv.lock", "pyproject.toml", "starpulse/web/pnpm-lock.yaml", ".github/*")
#: check -> (the changed paths it reads, those of them it does not). Paths are relative to the repository root.
#: `web` runs in `starpulse/web`; `contract` runs trantor's tests against the package, which never import this repository's
#: own tests or page; `static` includes `public_names`, which reads every tracked file, so any change reaches it.
READS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "web": (("starpulse/web/*", "starpulse/api.schema.json"), ()),
    "contract": (("*",), ("starpulse/web/*", "starpulse/tests/*", "docs/*", "design/*", "bench/*", "*.md")),
    "static": (("*",), ()),
}


def reaches(check: str, changed: Sequence[str]) -> bool:
    """Whether a change to these paths can alter `check`'s result; a change of no files reaches nothing."""
    reads, ignored = READS[check]

    def read(path: str) -> bool:
        if any(fnmatch(path, pattern) for pattern in FULL):
            return True
        return any(fnmatch(path, pattern) for pattern in reads) and not any(fnmatch(path, p) for p in ignored)

    return any(read(path) for path in changed)


def scope(changed: Sequence[str]) -> dict[str, bool]:
    return {check: reaches(check, changed) for check in READS}


def main() -> None:
    for check, reached in scope(sys.stdin.read().split()).items():
        print(f"{check}={str(reached).lower()}")


if __name__ == "__main__":
    main()
