"""The test files a pull request's changes can affect, or the full suite when that cannot be known from its paths.

    git diff --name-only HEAD^1 HEAD | python ci/select_tests.py >> "$GITHUB_ENV"

A changed Python module selects every test file that imports it directly or through other modules, read from the
import statements under `starpulse/` and `ci/`; a changed test file selects itself. A non-Python file selects the tests
of the Python files that read it (`READERS`), a file no test reads selects nothing (`INERT`), and a change whose
readers the import graph cannot name (`FULL_SUITE`, a deleted module, or any path this file does not know) runs
everything. A push to main runs the full suite regardless, so what a selection misses fails there.

Prints `PYTEST_TARGETS` (empty means the whole suite) and `PYTEST_SKIP` (true when no test is selected).
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

#: Read by every test, by pytest itself or by a loader the graph cannot follow (YAML, JSON, skill files).
FULL_SUITE = (
    "pyproject.toml",
    "uv.lock",
    "conftest.py",
    "*/conftest.py",
    "starpulse/tests/fixtures/*",
    "starpulse/machines/*",
    "starpulse/schemas/*",
    "*.schema.json",
    "starpulse/skills/*",
)

#: Non-Python files and the Python files that open them by path; each reader counts as changed.
READERS = {
    "README.md": ("starpulse/server.py", "starpulse/tests/unit/test_public_surface.py", "ci/ui_preview.py"),
    "starpulse/web/*": ("starpulse/tests/unit/test_neutrality.py", "ci/ui_preview.py"),
    "design/*": ("ci/ui_preview.py",),
    "ci/preview.toml": ("ci/ui_preview.py",),
    "starpulse/migrations/*": ("starpulse/hub.py",),
}

#: Workflow files are read by the `ci/` tests that assert on them.
WORKFLOWS = ".github/workflows/*"

#: Tracked files no test reads.
INERT = (
    "CONTRIBUTING.md",
    "LICENSE",
    ".gitignore",
    ".coderabbit.yaml",
    ".github/actionlint.yaml",
    ".github/ISSUE_TEMPLATE/*",
    ".github/pull_request_template.md",
    "bench/*",
)

#: `board.py` and `config.py` import an adapter by the name configuration gives (`importlib.import_module`), so a test
#: reaching either reaches each adapter whose name appears in a module it reaches: a configured `kind = "dagu"` in the
#: test or a helper, or the loader's own default (`board.DEFAULT_TYPE`).
NAMED_LOADERS = ("starpulse.board", "starpulse.config")


@dataclass(frozen=True)
class Selection:
    """Test files to run, sorted; `None` is the full suite."""

    tests: list[str] | None


FULL = Selection(None)


def _modules(root: Path) -> dict[str, Path]:
    """Importable module name -> file; `ci/` scripts are imported by bare name (`pythonpath = ["ci"]`)."""
    found = {}
    for path in (root / "starpulse").rglob("*.py"):
        rel = path.relative_to(root)
        if {"web", "__pycache__", "node_modules"} & set(rel.parts):
            continue
        parts = rel.with_suffix("").parts
        found[".".join(parts[:-1] if parts[-1] == "__init__" else parts)] = path
    found.update({path.stem: path for path in (root / "ci").glob("*.py")})
    return found


def _imports(module: str, path: Path) -> set[str]:
    """Every module name the file imports, with its parent packages, which importing it runs."""
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    names: set[str] = {module}
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join(parts + ([node.module] if node.module else []))
            names |= {base} | {f"{base}.{alias.name}" for alias in node.names}
    return {".".join(name.split(".")[:i]) for name in names for i in range(1, name.count(".") + 2)}


def _conftest_uses(path: Path) -> tuple[set[str], dict[str, set[str]]]:
    """The modules a conftest's own code uses, and those each of its fixtures uses, from the names it imports.

    pytest loads a `conftest.py` above every test file, but what its fixtures import matters only to a test that
    requests the fixture, by naming it.
    """
    tree = ast.parse(path.read_text())
    imported: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported[alias.asname or alias.name.split(".")[0]] = {alias.name}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                imported[alias.asname or alias.name] = {node.module, f"{node.module}.{alias.name}"}
    fixtures = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and any("fixture" in ast.unparse(d) for d in node.decorator_list)
    }

    def used(nodes: list[ast.AST]) -> set[str]:
        names, stack = set(), list(nodes)
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.Import, ast.ImportFrom)) or node in fixtures.values():
                continue
            if isinstance(node, ast.Name):
                names |= imported.get(node.id, set())
            stack.extend(ast.iter_child_nodes(node))
        return names

    uses = {name: used(list(node.body)) for name, node in fixtures.items()}
    requests = {
        name: {other for other in fixtures if other != name and re.search(rf"\b{other}\b", ast.unparse(node))}
        for name, node in fixtures.items()
    }  # a fixture requesting another, by parameter or `getfixturevalue`
    grew = True
    while grew:
        grew = False
        for name, others in requests.items():
            merged = uses[name].union(*(uses[other] for other in others))
            grew |= merged != uses[name]
            uses[name] = merged
    return used(tree.body), uses


def _is_adapter(path: Path) -> bool:
    """An adapter module defines a top-level `board`, or both `start` and `follow`."""
    defined = {node.name for node in ast.parse(path.read_text()).body if isinstance(node, ast.FunctionDef)}
    return "board" in defined or {"start", "follow"} <= defined


def select(root: Path, changed: list[str]) -> Selection:
    modules = _modules(root)
    module_of = {str(path.relative_to(root)): name for name, path in modules.items()}
    tests = {name for name, path in modules.items() if path.name.startswith("test_")}
    affected: set[str] = set()
    for path in changed:
        if any(fnmatch(path, pattern) for pattern in FULL_SUITE):
            return FULL
        if any(fnmatch(path, pattern) for pattern in INERT):
            continue
        if fnmatch(path, WORKFLOWS):
            affected |= {name for name in tests if modules[name].parent == root / "ci"}
            continue
        readers = next((files for pattern, files in READERS.items() if fnmatch(path, pattern)), None)
        if readers is not None:
            if not all(reader in module_of for reader in readers):
                return FULL
            affected |= {module_of[reader] for reader in readers}
        elif path in module_of:
            affected.add(module_of[path])
        else:
            return FULL  # a deleted module, or a path nothing here knows

    imports = {name: _imports(name, path) & modules.keys() for name, path in modules.items()}
    for conftest in (path for path in modules.values() if path.name == "conftest.py"):
        always, fixtures = _conftest_uses(conftest)
        for test in (t for t in tests if modules[t].is_relative_to(conftest.parent)):
            text = modules[test].read_text()
            requested = (uses for fixture, uses in fixtures.items() if re.search(rf"\b{fixture}\b", text))
            imports[test] |= always.union(*requested) & modules.keys()
    adapters = {
        name: name.rpartition(".")[2] for name, path in modules.items() if name.count(".") == 1 and _is_adapter(path)
    }

    def reaches(name: str) -> set[str]:
        """Modules `name` imports transitively, plus each adapter a loader it reaches would load by a name it holds."""
        seen, stack = {name}, [name]
        while stack:
            for dep in imports[stack.pop()] - seen:
                seen.add(dep)
                stack.append(dep)
            if not stack and seen & set(NAMED_LOADERS):
                text = "\n".join(modules[m].read_text() for m in seen)
                named = {a for a, word in adapters.items() if re.search(rf"\b{word}\b", text)} - seen
                seen |= named
                stack.extend(named)
        return seen

    return Selection(sorted(str(modules[t].relative_to(root)) for t in tests if reaches(t) & affected))


def main() -> None:
    selection = select(Path.cwd(), [line.strip() for line in sys.stdin if line.strip()])
    targets = selection.tests or []
    print(f"PYTEST_TARGETS={' '.join(targets)}")
    print(f"PYTEST_SKIP={'true' if selection.tests == [] else 'false'}")


if __name__ == "__main__":
    main()
