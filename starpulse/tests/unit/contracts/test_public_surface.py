"""The public surface is pinned: the modules docs/public-surface.md lists, the names each exports, and nothing else."""

import importlib
import re
from pathlib import Path

import pytest

#: Every module and name an adapter may import. Adding or removing one is a reviewed, public change.
PUBLIC: dict[str, set[str]] = {
    "starpulse.adapter_kit": {
        "BoardAdapterKit",
        "InsightsEngineKit",
        "MachineEventsAdapterKit",
        "RunsAdapterKit",
        "assembled",
        "next_event",
        "serve",
        "task",
        "url",
    },
    "starpulse.board": {
        "DEFAULT_TYPE",
        "AssigneeWriter",
        "Board",
        "DocArchiver",
        "DocCreator",
        "DocEditor",
        "DocLister",
        "DocReader",
        "DocRestorer",
        "MilestoneArchiver",
        "MilestoneCreator",
        "MilestoneEditor",
        "MilestoneLister",
        "MilestoneReader",
        "MoveWriter",
        "TaskArchiver",
        "TaskCompleter",
        "TaskCreator",
        "TaskEditor",
        "TaskReader",
        "TaskRestorer",
        "UpstreamBacklog",
        "Written",
        "load",
        "module_name",
    },
    "starpulse.board_feed": {"BoardFeed", "BoardStore", "Followed", "Resumable"},
    "starpulse.config": {"CommitKeys", "Config", "ConfigError", "Forward", "RunsInstance", "Source", "load", "runs_adapter"},
    "starpulse.contracts": {
        "CONTRACTS",
        "EVENT_STREAMS",
        "FINDING_TEXT_MAX",
        "SCHEMAS",
        "ActiveRun",
        "BoardTask",
        "Dag",
        "Evidence",
        "Finding",
        "FindingEngine",
        "FindingScope",
        "LaneEvent",
        "MachineEvent",
        "Move",
        "Pool",
        "RecentRun",
        "RunEvent",
        "RunStatus",
        "RunsSink",
        "StartFailedError",
        "Step",
        "TaskKeys",
    },
    "starpulse.event_log": {"Entry", "EventLog", "Tail"},
    "starpulse.harnesses": {"Harness", "HarnessError", "Harnesses", "Tier", "load_harnesses"},
    "starpulse.history": {"History", "machine_steps"},
    "starpulse.machine_definition": {
        "Compiled",
        "Cue",
        "MachineDefinitionError",
        "Registry",
        "Writer",
        "load_machine",
        "refuse_unlisted",
        "validate",
        "writers_of",
    },
    "starpulse.mermaid_import": {"Diagram", "Edge", "draft_machine", "dump", "parse"},
    "starpulse.otlp": {
        "ASSISTANT_RESPONSE",
        "BRANCH",
        "SKILL_ACTIVATED",
        "TOOL_RESULT",
        "USER_PROMPT",
        "LogEvent",
        "parse",
        "receiver",
    },
    "starpulse.snapshot": {"Qualify", "describe", "is_workflow", "qualifier", "writers"},
}

SURFACE = next(root for root in Path(__file__).resolve().parents if (root / "README.md").is_file()) / "docs/public-surface.md"


def _listed_on_the_page() -> set[str]:
    section = re.search(r"^## Public surface\n(.*?)(?=^## )", SURFACE.read_text(), re.MULTILINE | re.DOTALL)
    assert section, "docs/public-surface.md has no `## Public surface` section"
    return set(re.findall(r"^- `(starpulse\.[a-z_]+)`", section.group(1), re.MULTILINE))


def test_the_public_surface_page_lists_exactly_the_pinned_modules() -> None:
    assert _listed_on_the_page() == set(PUBLIC)


@pytest.mark.parametrize("module", sorted(PUBLIC))
def test_each_public_module_exports_exactly_its_pinned_names(module: str) -> None:
    imported = importlib.import_module(module)

    assert sorted(imported.__all__) == sorted(set(imported.__all__)), "a name is listed twice"
    assert set(imported.__all__) == PUBLIC[module]
    assert [name for name in PUBLIC[module] if not hasattr(imported, name)] == []


#: Root entries that are not a listed public module: the entry points, the internal code and the packages that ship data.
ROOT_OTHER = {"__init__", "__main__", "claude_code", "_internal", "tests"}


def _unlisted_at_root(package: Path) -> set[str]:
    """The Python modules and packages directly under `package` that neither docs/public-surface.md lists nor `ROOT_OTHER` allows."""
    found = {path.stem for path in package.glob("*.py")} | {path.parent.name for path in package.glob("*/__init__.py")}
    return found - {module.removeprefix("starpulse.") for module in PUBLIC} - ROOT_OTHER


def test_the_root_holds_only_the_public_surface_and_the_internal_package() -> None:
    """Everything that is not a public path lives under `_internal` (D1 of doc-130)."""
    package = Path(importlib.import_module("starpulse").__file__ or "").parent

    assert _unlisted_at_root(package) == set()


def test_every_listed_module_is_a_root_module() -> None:
    package = Path(importlib.import_module("starpulse").__file__ or "").parent
    top_level = {path.stem for path in package.glob("*.py")} | {path.parent.name for path in package.glob("*/__init__.py")}

    assert {module.removeprefix("starpulse.") for module in PUBLIC} <= top_level


@pytest.mark.parametrize("stray", ["stray.py", "stray/__init__.py"])
def test_an_unlisted_root_module_or_package_is_found(tmp_path: Path, stray: str) -> None:
    (tmp_path / stray).parent.mkdir(exist_ok=True)
    (tmp_path / stray).write_text("")
    (tmp_path / "board.py").write_text("")

    assert _unlisted_at_root(tmp_path) == {"stray"}


def test_the_board_feed_logs_under_its_public_path() -> None:
    assert importlib.import_module("starpulse._internal.feed.board_feed").logger.name == "starpulse.board_feed"


#: Test directories under a tier that mirror no `_internal` package: the public `contracts` package and the public surface.
TEST_DIRECTORIES_OTHER = {"contracts"}


def _misplaced_tests(tests: Path, features: set[str]) -> set[str]:
    """The `unit` and `integration` entries that are a test module directly in the tier, or a directory naming no feature."""
    return {
        f"{tier.name}/{entry.name}"
        for tier in (tests / "unit", tests / "integration")
        for entry in tier.iterdir()
        if (entry.is_file() and entry.name.startswith("test_"))
        or (entry.is_dir() and entry.name != "__pycache__" and entry.name not in features | TEST_DIRECTORIES_OTHER)
    }


def test_every_unit_and_integration_test_sits_in_the_directory_of_the_feature_package_it_tests() -> None:
    """Decision 3 of the layering ADR: the tests mirror `_internal` by feature (S4 of doc-130)."""
    package = Path(importlib.import_module("starpulse").__file__ or "").parent
    features = {path.name for path in (package / "_internal").iterdir() if (path / "__init__.py").is_file()}

    assert _misplaced_tests(package / "tests", features) == set()


@pytest.mark.parametrize(
    ("stray", "found"), [("test_stray.py", "unit/test_stray.py"), ("stray/test_stray.py", "unit/stray")]
)
def test_a_test_directly_in_a_tier_or_in_a_directory_naming_no_feature_is_found(
    tmp_path: Path, stray: str, found: str
) -> None:
    for tier in ("unit", "integration"):
        (tmp_path / tier / "board").mkdir(parents=True)
        (tmp_path / tier / "board" / "test_board.py").write_text("")
        (tmp_path / tier / "__init__.py").write_text("")
    (tmp_path / "unit" / stray).parent.mkdir(exist_ok=True)
    (tmp_path / "unit" / stray).write_text("")

    assert _misplaced_tests(tmp_path, {"board"}) == {found}
