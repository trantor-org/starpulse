"""Claude Code's OTLP/HTTP log events; the implementation is in `starpulse.harness_telemetry.otlp`."""

from starpulse.harness_telemetry.otlp import (
    ASSISTANT_RESPONSE,
    BRANCH,
    SKILL_ACTIVATED,
    TOOL_RESULT,
    USER_PROMPT,
    LogEvent,
    parse,
    receiver,
)

__all__ = [
    "ASSISTANT_RESPONSE",
    "BRANCH",
    "SKILL_ACTIVATED",
    "TOOL_RESULT",
    "USER_PROMPT",
    "LogEvent",
    "parse",
    "receiver",
]
