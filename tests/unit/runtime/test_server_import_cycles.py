"""No module of `starpulse.views` or `starpulse.runtime` imports itself back through the others, counting the imports made inside
functions as well: a function-level import is still an edge a worker's startup can follow."""

from __future__ import annotations

import ast
import importlib
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

import pytest


def _modules(package: str) -> dict[str, Path]:
    root = Path(importlib.import_module(package).__file__ or "").parent
    found = {}
    for path in root.glob("*.py"):
        name = package if path.name == "__init__.py" else f"{package}.{path.stem}"
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


@pytest.mark.parametrize("package", ["starpulse.views", "starpulse.runtime"])
def test_no_import_cycle_among_the_server_modules(package: str) -> None:
    modules = _modules(package)
    graph = {name: (_imported(path) & modules.keys()) - {name} for name, path in modules.items()}

    try:
        list(TopologicalSorter(graph).static_order())
    except CycleError as exc:
        raise AssertionError(f"import cycle: {' -> '.join(exc.args[1])}") from exc
