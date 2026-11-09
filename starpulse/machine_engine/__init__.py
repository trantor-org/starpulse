"""The Machine engine: how a lifecycle machine is defined, compiled, replayed and described, and the loaders that read one from a file."""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starpulse.machine_engine.adapters.machine_loader import load_machine, validate
    from starpulse.machine_engine.adapters.mermaid_import import Diagram, Edge, draft_machine, dump, parse
    from starpulse.machine_engine.model.graph import (
        Accepted,
        Bypass,
        Incomplete,
        Machine,
        Path,
        Step,
        Verdict,
        bypasses,
        conform,
        dominators,
        fitness,
        replay,
        runs,
        shortest_paths,
        simple_paths,
    )
    from starpulse.machine_engine.model.graph import Violation as TraceViolation
    from starpulse.machine_engine.model.machine_definition import (
        Compiled,
        Cue,
        MachineDefinitionError,
        Registry,
        Writer,
        refuse_unlisted,
        role_of,
        writers_of,
    )
    from starpulse.machine_engine.model.replay import Report, Violation, check_events, check_lanes
    from starpulse.machine_engine.model.snapshot import Qualify, describe, is_workflow, qualifier, writers

#: Each name and the module that defines it. They load on first use, so importing one submodule of the context does not
#: load the schema validator, the state-machine library or the database stack the others need.
_EXPORTS = {
    "load_machine": ("starpulse.machine_engine.adapters.machine_loader", "load_machine"),
    "validate": ("starpulse.machine_engine.adapters.machine_loader", "validate"),
    "Diagram": ("starpulse.machine_engine.adapters.mermaid_import", "Diagram"),
    "Edge": ("starpulse.machine_engine.adapters.mermaid_import", "Edge"),
    "draft_machine": ("starpulse.machine_engine.adapters.mermaid_import", "draft_machine"),
    "dump": ("starpulse.machine_engine.adapters.mermaid_import", "dump"),
    "parse": ("starpulse.machine_engine.adapters.mermaid_import", "parse"),
    "Accepted": ("starpulse.machine_engine.model.graph", "Accepted"),
    "Bypass": ("starpulse.machine_engine.model.graph", "Bypass"),
    "Incomplete": ("starpulse.machine_engine.model.graph", "Incomplete"),
    "Machine": ("starpulse.machine_engine.model.graph", "Machine"),
    "Path": ("starpulse.machine_engine.model.graph", "Path"),
    "Step": ("starpulse.machine_engine.model.graph", "Step"),
    "Verdict": ("starpulse.machine_engine.model.graph", "Verdict"),
    "bypasses": ("starpulse.machine_engine.model.graph", "bypasses"),
    "conform": ("starpulse.machine_engine.model.graph", "conform"),
    "dominators": ("starpulse.machine_engine.model.graph", "dominators"),
    "fitness": ("starpulse.machine_engine.model.graph", "fitness"),
    "replay": ("starpulse.machine_engine.model.graph", "replay"),
    "runs": ("starpulse.machine_engine.model.graph", "runs"),
    "shortest_paths": ("starpulse.machine_engine.model.graph", "shortest_paths"),
    "simple_paths": ("starpulse.machine_engine.model.graph", "simple_paths"),
    "TraceViolation": ("starpulse.machine_engine.model.graph", "Violation"),
    "Compiled": ("starpulse.machine_engine.model.machine_definition", "Compiled"),
    "Cue": ("starpulse.machine_engine.model.machine_definition", "Cue"),
    "MachineDefinitionError": ("starpulse.machine_engine.model.machine_definition", "MachineDefinitionError"),
    "Registry": ("starpulse.machine_engine.model.machine_definition", "Registry"),
    "Writer": ("starpulse.machine_engine.model.machine_definition", "Writer"),
    "refuse_unlisted": ("starpulse.machine_engine.model.machine_definition", "refuse_unlisted"),
    "role_of": ("starpulse.machine_engine.model.machine_definition", "role_of"),
    "writers_of": ("starpulse.machine_engine.model.machine_definition", "writers_of"),
    "Report": ("starpulse.machine_engine.model.replay", "Report"),
    "Violation": ("starpulse.machine_engine.model.replay", "Violation"),
    "check_events": ("starpulse.machine_engine.model.replay", "check_events"),
    "check_lanes": ("starpulse.machine_engine.model.replay", "check_lanes"),
    "Qualify": ("starpulse.machine_engine.model.snapshot", "Qualify"),
    "describe": ("starpulse.machine_engine.model.snapshot", "describe"),
    "is_workflow": ("starpulse.machine_engine.model.snapshot", "is_workflow"),
    "qualifier": ("starpulse.machine_engine.model.snapshot", "qualifier"),
    "writers": ("starpulse.machine_engine.model.snapshot", "writers"),
}

__all__ = [
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
]


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, attr = _EXPORTS[name]
    return getattr(importlib.import_module(module), attr)
