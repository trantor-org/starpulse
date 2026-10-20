"""Import every module an IC instance can load, in an environment without the Postgres driver.

    uv sync --locked --no-group postgres && uv run --no-sync python ci/ic_imports.py

A module an IC instance loads that imports the Postgres driver at import time fails here, in seconds, instead of in
a second run of the whole suite. `POSTGRES_ONLY` names the modules that import it directly; everything else under
`starpulse/` except the tests must import without it.
Prints each module that fails and exits 1.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterable
from pathlib import Path

POSTGRES_ONLY = ("starpulse._internal.eventlog.migrations",)


def ic_modules(root: Path) -> list[str]:
    """The dotted names of every non-test module under `root/starpulse` outside `POSTGRES_ONLY`."""
    names = (".".join(path.relative_to(root).with_suffix("").parts) for path in (root / "starpulse").rglob("*.py"))
    modules = (name.removesuffix(".__init__") for name in names)
    return sorted(m for m in modules if not m.startswith(POSTGRES_ONLY) and ".tests" not in m)


def failures(modules: Iterable[str]) -> list[tuple[str, str]]:
    """Each module that raised on import, with the exception it raised."""
    failed = []
    for module in modules:
        try:
            importlib.import_module(module)
        except Exception as error:  # any import-time error is a failure to report
            failed.append((module, f"{type(error).__name__}: {error}"))
    return failed


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    failed = failures(ic_modules(root))
    for module, error in failed:
        print(f"{module}: {error}")
    sys.exit(1 if failed else 0)
