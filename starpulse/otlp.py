"""Claude Code's OTLP/HTTP log events; the implementation is in `starpulse.adapters.harnesses.otlp`."""

from starpulse.adapters.harnesses.otlp import (
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
