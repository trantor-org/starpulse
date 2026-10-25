"""No module of `starpulse._internal.server` imports itself back through the others, counting the imports made inside
functions as well: a function-level import is still an edge a worker's startup can follow."""

from __future__ import annotations

import ast
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

import starpulse._internal.server as server_package

PACKAGE = "starpulse._internal.server"
ROOT = Path(server_package.__file__).parent


def _modules() -> dict[str, Path]:
    found = {}
    for path in ROOT.glob("*.py"):
        name = PACKAGE if path.name == "__init__.py" else f"{PACKAGE}.{path.stem}"
        found[name] = path
    return found


def _imported(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_no_import_cycle_among_the_server_modules() -> None:
    modules = _modules()
    graph = {name: (_imported(path) & modules.keys()) - {name} for name, path in modules.items()}

    try:
        list(TopologicalSorter(graph).static_order())
    except CycleError as exc:
        raise AssertionError(f"import cycle: {' -> '.join(exc.args[1])}") from exc
