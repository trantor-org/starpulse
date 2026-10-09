"""The public surface is pinned: the modules the README lists, the names each exports, and nothing else."""

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
        "UpstreamBacklog",
        "Written",
        "load",
        "module_name",
    },
    "starpulse.board_feed": {"BoardFeed", "BoardStore", "Followed", "Resumable"},
    "starpulse.config": {"CommitKeys", "Config", "ConfigError", "Forward", "RunsInstance", "Source", "load", "runs_adapter"},
    "starpulse.contracts": {
        "CONTRACTS",
        "FINDING_TEXT_MAX",
        "SCHEMAS",
        "ActiveRun",
        "BoardTask",
        "Dag",
        "Evidence",
        "Finding",
        "FindingEngine",
        "FindingScope",
        "MachineEvent",
        "Move",
        "Pool",
        "RecentRun",
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

README = next(root for root in Path(__file__).resolve().parents if (root / "README.md").is_file()) / "README.md"


def _listed_in_readme() -> set[str]:
    section = re.search(r"^## Public surface\n(.*?)(?=^## )", README.read_text(), re.MULTILINE | re.DOTALL)
    assert section, "the README has no `## Public surface` section"
    return set(re.findall(r"^- `(starpulse\.[a-z_]+)`", section.group(1), re.MULTILINE))


def test_the_readme_lists_exactly_the_pinned_modules() -> None:
    assert _listed_in_readme() == set(PUBLIC)


@pytest.mark.parametrize("module", sorted(PUBLIC))
def test_each_public_module_exports_exactly_its_pinned_names(module: str) -> None:
    imported = importlib.import_module(module)

    assert sorted(imported.__all__) == sorted(set(imported.__all__)), "a name is listed twice"
    assert set(imported.__all__) == PUBLIC[module]
    assert [name for name in PUBLIC[module] if not hasattr(imported, name)] == []


#: Root entries that are not a listed public module: the entry points, the internal code and the packages that ship data.
ROOT_OTHER = {"__init__", "__main__", "claude_code", "_internal", "tests"}


def _unlisted_at_root(package: Path) -> set[str]:
    """The Python modules and packages directly under `package` that neither the README lists nor `ROOT_OTHER` allows."""
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
