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
        "MoveWriter",
        "TaskArchiver",
        "TaskCreator",
        "TaskEditor",
        "TaskReader",
        "Written",
        "load",
        "module_name",
    },
    "starpulse.board_feed": {"BoardFeed", "BoardStore", "Followed", "Resumable"},
    "starpulse.config": {"Config", "ConfigError", "Forward", "RunsInstance", "Source", "load", "runs_adapter"},
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
