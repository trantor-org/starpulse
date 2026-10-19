"""Fail each tracked production module of this repository over trantor's busy-module limit, past any split-pending date.

trantor's `check-config` fails a pinned starpulse module changed in the last 90 days that is over 1,500 lines, but only on
a trantor commit after the pin bump has taken it in. Running it here keeps such a commit from going green. The limit, the
production-file patterns and the `SPLIT_PENDING` list are read from trantor's `linting.check_config_checks.busy_modules`,
so the two never drift. A CI clone holds no 90-day history, so every tracked module counts, not only the busy ones.

Usage: python ci/busy_modules.py <trantor>/lib
"""

from __future__ import annotations

import datetime
import subprocess
import sys
import types
from pathlib import Path


def violations(lib: Path, root: Path, today: str) -> list[str]:
    """One message per production module tracked under *root* that is over the limit with no entry lasting to *today*."""
    sys.path.insert(0, str(lib))
    # Its history read needs trantor's `git_cli` and the settings stack under it, outside starpulse's dependencies; the
    # constants read here never call it.
    sys.modules.setdefault("git_cli", types.ModuleType("git_cli"))
    from linting.check_config_checks import busy_modules as busy

    subdir, pathspecs, package_of = next(entry for entry in busy.REPOS if entry[0] == "starpulse")
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", *pathspecs], check=True, capture_output=True, text=True
    ).stdout.splitlines()
    messages = []
    for module in tracked:
        production = (
            busy.PRODUCTION.search(module) and not busy.TEST.search(module) and not busy.GENERATED.search(module)
        )
        if not (production and package_of.match(module) and (root / module).is_file()):
            continue
        lines = len((root / module).read_text(errors="replace").splitlines())
        until, _task = busy.SPLIT_PENDING.get(f"{subdir}/{module}", ("", ""))
        if lines > busy.LIMIT and until < today:
            messages.append(f"{module} is {lines} lines, over {busy.LIMIT}: split it by responsibility ({busy.RULE})")
    return messages


def main(lib: str) -> int:
    root = Path(__file__).resolve().parents[1]
    messages = violations(Path(lib).resolve(), root, datetime.date.today().isoformat())
    for message in messages:
        print(f"::error::{message}")
    return 1 if messages else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
