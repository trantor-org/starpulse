"""Import every module an IC instance can load, in an environment without the hub extras.

    uv sync --locked --no-group hub && uv run --no-sync python ci/ic_imports.py

An IC instance is `starpulse serve` without `--hub`. A module it loads that imports Alembic, the Postgres driver or
PyJWT at import time fails here, in seconds, instead of in a second run of the whole suite. `HUB_ONLY` names the
modules that import a hub extra directly; everything else under `starpulse/` except the tests must import without one.
Prints each module that fails and exits 1.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterable
from pathlib import Path

HUB_ONLY = ("starpulse._internal.hub.hub", "starpulse._internal.hub.oidc", "starpulse._internal.eventlog.migrations")


def ic_modules(root: Path) -> list[str]:
    """The dotted names of every non-test module under `root/starpulse` outside `HUB_ONLY`."""
    names = (".".join(path.relative_to(root).with_suffix("").parts) for path in (root / "starpulse").rglob("*.py"))
    modules = (name.removesuffix(".__init__") for name in names)
    return sorted(m for m in modules if not m.startswith(HUB_ONLY) and ".tests" not in m)


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
