"""Harness adapters: Claude Code, Codex and the OTLP receiver, and the harness tiers."""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starpulse.harness_telemetry.model.harnesses import Harness, HarnessError, Harnesses, Tier, load_harnesses
    from starpulse.harness_telemetry.adapters.inbound.otlp import (
        ASSISTANT_RESPONSE,
        BRANCH,
        SKILL_ACTIVATED,
        TOOL_RESULT,
        USER_PROMPT,
        LogEvent,
        parse,
        receiver,
    )

#: Each name and the module that defines it. They load on first use, so importing one submodule of the context does not
#: load the schema validator, the state-machine library or the database stack the others need.
_EXPORTS = {
    "Harness": ("starpulse.harness_telemetry.model.harnesses", "Harness"),
    "HarnessError": ("starpulse.harness_telemetry.model.harnesses", "HarnessError"),
    "Harnesses": ("starpulse.harness_telemetry.model.harnesses", "Harnesses"),
    "Tier": ("starpulse.harness_telemetry.model.harnesses", "Tier"),
    "load_harnesses": ("starpulse.harness_telemetry.model.harnesses", "load_harnesses"),
    "ASSISTANT_RESPONSE": ("starpulse.harness_telemetry.adapters.inbound.otlp", "ASSISTANT_RESPONSE"),
    "BRANCH": ("starpulse.harness_telemetry.adapters.inbound.otlp", "BRANCH"),
    "SKILL_ACTIVATED": ("starpulse.harness_telemetry.adapters.inbound.otlp", "SKILL_ACTIVATED"),
    "TOOL_RESULT": ("starpulse.harness_telemetry.adapters.inbound.otlp", "TOOL_RESULT"),
    "USER_PROMPT": ("starpulse.harness_telemetry.adapters.inbound.otlp", "USER_PROMPT"),
    "LogEvent": ("starpulse.harness_telemetry.adapters.inbound.otlp", "LogEvent"),
    "parse": ("starpulse.harness_telemetry.adapters.inbound.otlp", "parse"),
    "receiver": ("starpulse.harness_telemetry.adapters.inbound.otlp", "receiver"),
}

__all__ = [
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
]


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, attr = _EXPORTS[name]
    return getattr(importlib.import_module(module), attr)
