"""The public surface is pinned: the packages and modules docs/public-surface.md lists, the names each exports, and nothing else."""

import importlib
import re
from pathlib import Path

import pytest

#: Every context package and name an adapter may import. Adding or removing one is a reviewed, public change.
PUBLIC: dict[str, set[str]] = {
    "starpulse.board": {
        "DEFAULT_TYPE",
        "AssigneeWriter",
        "Board",
        "BoardFeed",
        "BoardStore",
        "CommitKeys",
        "DocArchiver",
        "DocCreator",
        "DocEditor",
        "DocLister",
        "DocReader",
        "DocRestorer",
        "Followed",
        "MilestoneArchiver",
        "MilestoneCreator",
        "MilestoneEditor",
        "MilestoneLister",
        "MilestoneReader",
        "MoveWriter",
        "Resumable",
        "RetiredImporter",
        "RetiredReader",
        "TaskArchiver",
        "TaskCompleter",
        "TaskCreator",
        "TaskEditor",
        "TaskReader",
        "TaskRestorer",
        "TaskRetirer",
        "UpstreamBacklog",
        "Written",
        "load",
        "module_name",
    },
    "starpulse.contracts": {
        "CONTRACTS",
        "EVENT_STREAMS",
        "SCHEMAS",
        "ActiveRun",
        "BoardTask",
        "Dag",
        "LaneEvent",
        "MachineEvent",
        "Move",
        "Pool",
        "RatingEvent",
        "RecentRun",
        "RunEvent",
        "RunStatus",
        "RunsSink",
        "StartFailedError",
        "Step",
        "TaskKeys",
    },
    "starpulse.event_log": {"Entry", "EventLog", "Tail"},
    "starpulse.flow_metrics": {"History", "machine_steps"},
    "starpulse.harness_telemetry": {
        "ASSISTANT_RESPONSE",
        "BRANCH",
        "SKILL_ACTIVATED",
        "TOOL_RESULT",
        "USER_PROMPT",
        "Harness",
        "HarnessError",
        "Harnesses",
        "LogEvent",
        "Tier",
        "load_harnesses",
        "parse",
        "receiver",
    },
    "starpulse.machine_engine": {
        "Accepted",
        "Bypass",
        "Compiled",
        "Cue",
        "Diagram",
        "Edge",
        "Incomplete",
        "Machine",
        "MachineDefinitionError",
        "Path",
        "Qualify",
        "Registry",
        "Report",
        "Step",
        "TraceViolation",
        "Verdict",
        "Violation",
        "Writer",
        "bypasses",
        "check_events",
        "check_lanes",
        "conform",
        "describe",
        "dominators",
        "draft_machine",
        "dump",
        "fitness",
        "is_workflow",
        "load_machine",
        "parse",
        "qualifier",
        "refuse_unlisted",
        "replay",
        "role_of",
        "runs",
        "shortest_paths",
        "simple_paths",
        "validate",
        "writers",
        "writers_of",
    },
    "starpulse.runs": {"RunsInstance"},
    "starpulse.sessions": {
        "SHELLS",
        "SHELL_OTHER",
        "SHELL_READ",
        "SHELL_SEARCH",
        "TOOL_OTHER",
        "SessionHealth",
        "SliceHealth",
        "TokenCounts",
        "activities",
        "session_health",
        "slice_health",
    },
}

#: The `runtime` modules an adapter may import, with the names each must export (the module's `__all__` may hold more).
RUNTIME: dict[str, set[str]] = {
    "starpulse.runtime.adapter_kit": {
        "BoardAdapterKit",
        "MachineEventsAdapterKit",
        "RunsAdapterKit",
        "assembled",
        "next_event",
        "serve",
        "task",
        "url",
    },
    "starpulse.runtime.closure": {"CONFIG_OWNERS", "restarts_serve"},
    "starpulse.runtime.config": {"Config", "ConfigError", "load", "runs_adapter"},
    "starpulse.runtime.write_instance": {"WriteInstance", "write_instance"},
}

SURFACE = (
    next(root for root in Path(__file__).resolve().parents if (root / "README.md").is_file()) / "docs/public-surface.md"
)


def _listed_on_the_page() -> set[str]:
    section = re.search(r"^## Public surface\n(.*?)(?=^#{2,3} )", SURFACE.read_text(), re.MULTILINE | re.DOTALL)
    assert section, "docs/public-surface.md has no `## Public surface` section"
    return set(re.findall(r"^- `(starpulse\.[a-z_.]+)`", section.group(1), re.MULTILINE))


def test_the_public_surface_page_lists_exactly_the_pinned_modules() -> None:
    assert _listed_on_the_page() == set(PUBLIC) | set(RUNTIME)


@pytest.mark.parametrize("module", sorted(PUBLIC))
def test_each_public_package_exports_exactly_its_pinned_names(module: str) -> None:
    imported = importlib.import_module(module)

    assert sorted(imported.__all__) == sorted(set(imported.__all__)), "a name is listed twice"
    assert set(imported.__all__) == PUBLIC[module]
    assert [name for name in PUBLIC[module] if not hasattr(imported, name)] == []


@pytest.mark.parametrize("module", sorted(RUNTIME))
def test_each_public_runtime_module_has_its_pinned_names(module: str) -> None:
    imported = importlib.import_module(module)

    assert [name for name in RUNTIME[module] if not hasattr(imported, name)] == []


#: The top level is exactly the bounded contexts, the kernel and the roots (D1 of doc-966).
ROOT = {
    "__init__",
    "__main__",
    "board",
    "cli",
    "contracts",
    "event_log",
    "flow_metrics",
    "github",
    "harness_telemetry",
    "machine_engine",
    "machines",
    "pulls",
    "runs",
    "runtime",
    "scheduler",
    "schemas",
    "sessions",
    "skills",
    "views",
    "web",
}


def _at_root(package: Path) -> set[str]:
    """The Python modules and packages directly under `package`, and the data directories the wheel ships.

    `static` is the page build, not a context: `ci/test_first_install.py` stubs it for the length of a test, and a
    worker of the same shard may list the package then.
    """
    return {path.stem for path in package.glob("*.py")} | {
        path.name for path in package.iterdir() if path.is_dir() and path.name not in {"__pycache__", "static"}
    }


def test_the_root_holds_only_the_contexts_the_kernel_and_the_roots() -> None:
    package = Path(importlib.import_module("starpulse").__file__ or "").parent

    assert _at_root(package) == ROOT


def test_every_public_package_is_a_root_package() -> None:
    package = Path(importlib.import_module("starpulse").__file__ or "").parent

    assert {module.removeprefix("starpulse.") for module in PUBLIC} <= _at_root(package)


def test_a_stray_root_module_or_package_is_found(tmp_path: Path) -> None:
    (tmp_path / "stray").mkdir()
    (tmp_path / "board.py").write_text("")

    assert _at_root(tmp_path) == {"stray", "board"}


def test_the_board_feed_logs_under_its_module_path() -> None:
    assert importlib.import_module("starpulse.board.board_feed").logger.name == "starpulse.board.board_feed"


#: Test directories under a tier that name no top-level package: the `leaks` gate that measures memory across every
#: context, and `server`, the end-to-end `serve` tests of the integration tier.
TEST_DIRECTORIES_OTHER = {"leaks", "server"}


def _misplaced_tests(tests: Path, packages: set[str]) -> set[str]:
    """The `unit` and `integration` entries that are a test module directly in the tier, or a directory naming no package."""
    return {
        f"{tier.name}/{entry.name}"
        for tier in (tests / "unit", tests / "integration")
        for entry in tier.iterdir()
        if (entry.is_file() and entry.name.startswith("test_"))
        or (entry.is_dir() and entry.name != "__pycache__" and entry.name not in packages | TEST_DIRECTORIES_OTHER)
    }


def test_every_unit_and_integration_test_sits_in_the_directory_of_the_package_it_tests() -> None:
    """Decision 3 of the layering ADR: the tests mirror the top-level packages."""
    tests = next(root for root in Path(__file__).resolve().parents if (root / "README.md").is_file()) / "tests"

    assert _misplaced_tests(tests, ROOT) == set()


@pytest.mark.parametrize(
    ("stray", "found"), [("test_stray.py", "unit/test_stray.py"), ("stray/test_stray.py", "unit/stray")]
)
def test_a_test_directly_in_a_tier_or_in_a_directory_naming_no_package_is_found(
    tmp_path: Path, stray: str, found: str
) -> None:
    for tier in ("unit", "integration"):
        (tmp_path / tier / "board").mkdir(parents=True)
        (tmp_path / tier / "board" / "test_board.py").write_text("")
        (tmp_path / tier / "__init__.py").write_text("")
    (tmp_path / "unit" / stray).parent.mkdir(exist_ok=True)
    (tmp_path / "unit" / stray).write_text("")

    assert _misplaced_tests(tmp_path, {"board"}) == {found}
