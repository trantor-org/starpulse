"""The test files a pull request's changes can affect, or the full suite when that cannot be known from its paths.

    git diff --name-only HEAD^1 HEAD | python ci/select_tests.py >> "$GITHUB_OUTPUT"

The newest coverage map the nightly published (`ci/coverage_map.py`) decides first: a changed file selects the tests
whose recorded run executed it, and a changed test file selects itself. A file the map does not name (a new file, or a
module only imported) falls back to the import graph read from the import statements under `starpulse/` and `ci/`: it
selects every test file that imports it directly or through other modules. A non-Python file selects the tests of the
Python files that read it (`READERS`), each reader as changed as the file it opens, a file no test reads selects nothing
(`INERT`), and a change whose readers cannot be named (`FULL_SUITE`: a dependency, `conftest.py`, a fixture, or a
`pyproject.toml` edit outside `LINT_TABLES`, told apart with `--base`; a deleted module; or any path this file does not
know) runs everything. A push to main selects the same way; the nightly scheduled run is the full suite, so what a
selection misses fails there.

Prints `PYTEST_TARGETS` (empty means the whole suite) and `PYTEST_SHARDS` (a JSON list of the shard indexes to launch:
empty when no test is selected, all six for a full run). `--full` prints the whole suite without reading a diff;
`--base REF` names the commit the diff starts from.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from fnmatch import fnmatch
from functools import cache
from pathlib import Path

from coverage_map import DEFAULT_DIR, latest
from shard import SECONDS

#: Read by every test, by pytest itself or by a loader the graph cannot follow (YAML, JSON, skill files).
FULL_SUITE = (
    "pyproject.toml",  # unless its edit is only to `LINT_TABLES`
    "uv.lock",
    "conftest.py",
    "*/conftest.py",
    "starpulse/tests/fixtures/*",
)

#: The `[tool.*]` tables of `pyproject.toml` that only a lint step reads; an edit to nothing else leaves every test's
#: inputs as they were.
LINT_TABLES = ("importlinter",)

#: Source files whose importers check the import in a subprocess, which the nightly coverage run does not trace, so the
#: map never lists those tests for them.
SUBPROCESS_IMPORTERS = {
    "starpulse/_internal/server/server.py": (
        "starpulse/tests/unit/server/test_serve_imports.py",
        "starpulse/tests/integration/server/test_serve_start.py",
        "starpulse/tests/integration/server/test_supervisor_lifetime.py",
    ),
}

#: Non-Python files and the Python files that open them by path; each reader counts as changed.
READERS = {
    "README.md": ("starpulse/_internal/server/server.py", "ci/ui_preview.py"),
    "docs/public-surface.md": ("starpulse/tests/unit/contracts/test_public_surface.py",),
    "starpulse/web/*": ("starpulse/tests/unit/contracts/test_neutrality.py", "ci/ui_preview.py"),
    "design/*": ("ci/ui_preview.py",),
    ".claude-plugin/*": ("starpulse/tests/integration/cli/test_agent_cli.py",),
    "docs/consumers.md": ("starpulse/tests/unit/event_log/test_consumer_pattern.py",),
    "docs/serving.md": ("starpulse/tests/unit/config/test_builtin_types.py",),
    "docs/sources.md": ("starpulse/tests/unit/config/test_builtin_types.py",),
    "ci/preview.toml": ("ci/ui_preview.py", "ci/seeded_server.py"),
    "starpulse/schemas/api.schema.json": ("starpulse/contracts/api/schema.py", "starpulse/contracts/api/__main__.py"),
    "starpulse/schemas/machine.schema.json": ("starpulse/machine_engine/adapters/machine_loader.py",),
    "starpulse/schemas/*": (
        "starpulse/contracts/adapters.py",
        "starpulse/contracts/__main__.py",
        "starpulse/tests/unit/contracts/test_contracts.py",
    ),
    "starpulse/event_log/migrations/*": ("starpulse/event_log/event_log.py",),
    "pyproject.toml": (),
    "ci/static_checks.sh": ("ci/test_workflow_placement.py",),
    "starpulse/machines/*": (
        "starpulse/pulls/ci.py",
        "starpulse/_internal/harnesses/harness.py",
        "starpulse/pulls/github.py",
        "starpulse/tests/unit/machine_engine/test_github_pull_request_machine.py",
    ),
    "starpulse/skills/*": (
        "starpulse/_internal/cli/skill_install.py",
        "starpulse/tests/integration/cli/test_agent_cli.py",
    ),
    "bench/page_latency.py": ("ci/test_page_latency.py", "ci/test_soak.py", "ci/test_load.py"),
    "bench/soak.py": ("ci/test_soak.py",),
    "bench/load.py": ("ci/test_load.py",),
}

#: Workflow files are read by the `ci/` tests that assert on them.
WORKFLOWS = ".github/workflows/*"

#: Tracked files no test reads.
INERT = (
    "CONTRIBUTING.md",
    "docs/adapters.md",
    "docs/cli.md",
    "docs/development.md",
    "docs/development-loop.md",
    "docs/security.md",
    "LICENSE",
    ".gitignore",
    ".coderabbit.yaml",
    ".github/actionlint.yaml",
    ".github/ISSUE_TEMPLATE/*",
    ".github/pull_request_template.md",
    "bench/README.md",
    "bench/flow_reads.py",
    "bench/free_threading/*",  # the interpreter A/B image and its scripts, run by hand
    "bench/ic_event_log.py",
)

#: The board seam and `config.py` import an adapter by the name configuration gives (`importlib.import_module`), so a
#: test reaching either reaches each adapter whose name appears in a module it reaches: a configured `kind = "dagu"` in
#: the test or a helper, or the loader's own default (`config.DEFAULT_TYPE`).
NAMED_LOADERS = ("starpulse._internal.board.seam", "starpulse._internal.config.config")

#: The feature packages that hold adapters; a module directly in one of them may be an adapter.
ADAPTER_PACKAGES = tuple(f"starpulse._internal.{package}." for package in ("board", "runs", "pulls", "harnesses"))

#: The module that lists every built-in adapter's name. Every loader reaches it, so its text names no adapter a test
#: names: it would otherwise select every adapter's tests for a change to any loader.
TYPE_TABLE = "starpulse._internal.config.adapter_types"


@dataclass(frozen=True)
class Selection:
    """Test files to run, sorted; `None` is the full suite."""

    tests: list[str] | None


FULL = Selection(None)

#: Shards a full run splits the suite across (`ci/shard.py`).
SHARD_COUNT = 6

#: Seconds of tests a selected shard should hold, about what its checkout and `uv sync` cost: a smaller share does not
#: pay for the runner it holds. A selected file `ci/shard.py` has not weighed counts `FILE_SECONDS`.
SHARD_SECONDS = 60
FILE_SECONDS = 5


def shards_for(selection: Selection) -> list[int]:
    """The 1-based shard indexes to launch: all of them for a full run, none for no test, else by the files' weight.

    Never more than the files: `ci/shard.py` never splits one.
    """
    if selection.tests is None:
        return list(range(1, SHARD_COUNT + 1))
    seconds = sum(SECONDS.get(test, FILE_SECONDS) for test in selection.tests)
    return list(range(1, min(SHARD_COUNT, len(selection.tests), -(-seconds // SHARD_SECONDS)) + 1))


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


def _module_name(path: str) -> str:
    """The module name `_modules` gives a `.py` file path, whether or not the file exists."""
    parts = Path(path).with_suffix("").parts
    return parts[-1] if parts[0] == "ci" else ".".join(parts)


def _imports(module: str, path: Path) -> frozenset[str]:
    """Every module name the file imports, with its parent packages, which importing it runs."""
    return _imports_of(module, path.name == "__init__.py", path.read_text())


@cache
def _imports_of(module: str, is_package: bool, text: str) -> frozenset[str]:
    """`_imports` keyed on the source, so a process that selects again parses each file once."""
    package = module if is_package else module.rpartition(".")[0]
    names: set[str] = {module}
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join(parts + ([node.module] if node.module else []))
            names |= {base} | {f"{base}.{alias.name}" for alias in node.names}
    return frozenset(".".join(name.split(".")[:i]) for name in names for i in range(1, name.count(".") + 2))


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


def _covering(coverage: dict | None) -> dict[str, set[str]]:
    """Source file -> the test files with a test that ran it, from the nightly coverage map (`ci/coverage_map.py`)."""
    covering: dict[str, set[str]] = {}
    for nodeid, files in (coverage or {"tests": {}})["tests"].items():
        for file in files:
            covering.setdefault(file, set()).add(nodeid.partition("::")[0])
    return covering


def _only_lint_tables(root: Path, before: str | None) -> bool:
    """Whether `pyproject.toml` differs from its `before` text only in `LINT_TABLES`; without a `before`, it may not."""
    if before is None:
        return False

    def without_lint(text: str) -> dict:
        config = tomllib.loads(text)
        for table in LINT_TABLES:
            config.get("tool", {}).pop(table, None)
        return config

    try:
        return without_lint(before) == without_lint((root / "pyproject.toml").read_text())
    except tomllib.TOMLDecodeError:
        return False


def _route(
    root: Path,
    changed: list[str],
    covering: dict[str, set[str]],
    modules: dict[str, Path],
    pyproject_before: str | None,
) -> tuple[set[str], set[str]] | None:
    """The test files the map names and the modules whose importers are affected, or None when only the full suite is safe."""
    module_of = {str(path.relative_to(root)): name for name, path in modules.items()}
    tests = {name for name, path in modules.items() if path.name.startswith("test_")}
    covered: set[str] = set()
    affected: set[str] = set()
    pending = list(changed)
    while pending:
        path = pending.pop()
        if path in covering:  # the map names the tests that ran it; the rules below are for what it never saw
            covered |= covering[path] | set(SUBPROCESS_IMPORTERS.get(path, ()))
            if Path(path).name.startswith("test_") and path.endswith(".py"):
                covered.add(path)  # a changed test file selects itself
            continue
        if path == "pyproject.toml" and _only_lint_tables(root, pyproject_before):
            pending.extend(READERS[path])
            continue
        if any(fnmatch(path, pattern) for pattern in FULL_SUITE):
            return None
        if any(fnmatch(path, pattern) for pattern in INERT):
            continue
        if fnmatch(path, WORKFLOWS):
            affected |= {name for name in tests if modules[name].parent == root / "ci"}
            continue
        readers = next((files for pattern, files in READERS.items() if fnmatch(path, pattern)), None)
        if readers is not None:
            if not all(reader in module_of for reader in readers):
                return None
            pending.extend(readers)  # each reader is as changed as the file it opens
        elif path in module_of:
            affected.add(module_of[path])
        elif Path(path).name.startswith("test_") and path.endswith(".py"):
            continue  # a deleted test file takes its tests with it
        elif _module_name(path) in modules:
            affected.add(_module_name(path))  # a module replaced by a package: importers still import the name
        else:
            return None  # a deleted module, or a path nothing here knows
    return covered, affected


def select(
    root: Path, changed: list[str], coverage: dict | None = None, pyproject_before: str | None = None
) -> Selection:
    modules = _modules(root)
    covering = _covering(coverage)
    routed = _route(root, changed, covering, modules, pyproject_before)
    if routed is None:
        return FULL
    covered, affected = routed
    module_of = {str(path.relative_to(root)): name for name, path in modules.items()}
    path_of = {name: path for path, name in module_of.items()}
    tests = {name for name, path in modules.items() if path.name.startswith("test_")}
    imports = {name: _imports(name, path) & modules.keys() for name, path in modules.items()}
    for conftest in (path for path in modules.values() if path.name == "conftest.py"):
        always, fixtures = _conftest_uses(conftest)
        for test in (t for t in tests if modules[t].is_relative_to(conftest.parent)):
            text = modules[test].read_text()
            requested = (uses for fixture, uses in fixtures.items() if re.search(rf"\b{fixture}\b", text))
            imports[test] |= always.union(*requested) & modules.keys()
    adapters = {
        name: name.rpartition(".")[2]
        for name, path in modules.items()
        if name.startswith(ADAPTER_PACKAGES) and name.count(".") == 3 and _is_adapter(path)
    }

    @cache
    def names(module: str) -> frozenset[str]:
        """The adapters whose name `module` holds as a word, read once however many tests reach it."""
        text = modules[module].read_text()
        return frozenset(a for a, word in adapters.items() if re.search(rf"\b{word}\b", text))

    def reaches(name: str) -> set[str]:
        """Modules `name` imports transitively, plus each adapter a loader it reaches would load by a name it holds.

        A module the map names but not for this test is only imported by it, so what it imports does not count.
        """
        test = path_of[name]
        seen, stack = {name}, [name]
        while stack:
            module = stack.pop()
            if test in covering.get(path_of[module], (test,)):
                for dep in imports[module] - seen:
                    seen.add(dep)
                    stack.append(dep)
            if not stack and seen & set(NAMED_LOADERS):
                named = set().union(*(names(m) for m in seen - {TYPE_TABLE})) - seen
                seen |= named
                stack.extend(named)
        return seen

    reached = {str(modules[t].relative_to(root)) for t in tests if reaches(t) & affected}
    return Selection(sorted(reached | {test for test in covered if (root / test).is_file()}))


def _file_at(root: Path, ref: str, path: str) -> str | None:
    """`path` as `ref` held it, or None when git cannot show it."""
    shown = subprocess.run(["git", "-C", str(root), "show", f"{ref}:{path}"], capture_output=True, text=True)
    return shown.stdout if shown.returncode == 0 else None


def main(argv: list[str]) -> None:
    """Print the selection for the diff on stdin, or the whole suite for `--full` (the schedule, a dispatch: no diff).

    `--base REF` names the commit the diff starts from, so an edit to `pyproject.toml` can be told from a dependency one.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--base")
    args = parser.parse_args(argv)
    if args.full:
        selection = FULL
    else:
        changed = [line.strip() for line in sys.stdin if line.strip()]
        before = _file_at(Path.cwd(), args.base, "pyproject.toml") if args.base else None
        selection = select(Path.cwd(), changed, latest(DEFAULT_DIR), before)
    targets = selection.tests or []
    print(f"PYTEST_TARGETS={' '.join(targets)}")
    print(f"PYTEST_SHARDS={json.dumps(shards_for(selection))}")


if __name__ == "__main__":
    main(sys.argv[1:])
