"""Fail when a tracked file names one of the operator's private hosts, or a shipped skill or machine names Trantor.

    python ci/public_names.py

This repository is public, so prose, comments, fixtures and mock data use neutral names. Exempt: workflow files and
the runner-label list actionlint reads for them (a runner label is functional), and tests (which may build a denied
name to prove a check). Prints one `path:line: name` row per match and exits 1 when
there are any.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

# Each name has one character in a class so this line does not match its own patterns.
DENIED = re.compile(r"ai-v[m](-\d+)?|unrai[d]|proxmo[x]|\bTowe[r]\b", re.IGNORECASE)
CANDIDATE = re.compile(r"ai-v[m]|unrai[d]|proxmo[x]|towe[r]")  # DENIED's names, lowercased and loosened, to skip files that cannot match
EXEMPT =re.compile(r"^\.github/(workflows/|actionlint\.yaml$)|(^|/)(tests/|test_[^/]*$)")
# Trantor names are refused under starpulse/skills and starpulse/machines, which ship in the public package (the public-package ADR).
SHIPPED = re.compile(r"^starpulse/(skills|machines)/")
TRANTOR = re.compile(r"trantor|backlog-task|\.venv/bin/|bin/workspace|agent-cmd", re.IGNORECASE)


def violations(files: Iterable[Path], root: Path) -> list[str]:
    rows = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        if EXEMPT.search(rel):
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError, OSError:  # a binary file, or a tracked symlink to nothing
            continue
        if not CANDIDATE.search(text.lower()):  # one scan skips the per-line IGNORECASE alternation on the ~98% of files that hold no name
            continue
        lines = text.splitlines()
        rows += [f"{rel}:{n}: {m.group()}" for n, line in enumerate(lines, 1) for m in DENIED.finditer(line)]
    return rows


def trantor_violations(files: Iterable[Path], root: Path) -> list[str]:
    rows = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        if not SHIPPED.search(rel) or EXEMPT.search(rel):
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError, OSError:  # a binary file, or a tracked symlink to nothing
            continue
        rows += [f"{rel}:{n}: {m.group()}" for n, line in enumerate(text.splitlines(), 1) for m in TRANTOR.finditer(line)]
    return rows


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    files = [root / p for p in tracked.decode().split("\0") if p]
    rows = violations(files, root) + trantor_violations(files, root)
    print("\n".join(rows))
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())
