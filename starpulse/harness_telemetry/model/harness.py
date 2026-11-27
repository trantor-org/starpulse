"""The shared session events: one agent session's start, the skills and tools it uses, and its stop.

Any harness adapter writes these events, so the table depends on no project's hooks or conventions. It is declared
here, never as a machine file; each adapter's `events` map names the hook events and log records that fire them.
"""

from pathlib import Path

from starpulse.machine_engine.model.machine_definition import compile_document
from starpulse.machine_engine.model.snapshot import describe

_ALL = ["idle", "active", "stopped", "ended"]
_TABLE = {
    "name": "harness",
    "states": {"idle": {"initial": True}, "active": {}, "stopped": {}, "ended": {}},
    "events": {
        "SESSION_STARTED": [{"from": _ALL, "to": "active"}],
        "SESSION_DISPATCHED": [{"from": _ALL, "to": "active"}],
        "SKILL_USED": [{"from": ["active", "stopped"], "to": "active"}],
        "TOOL_USED": [{"from": ["active", "stopped"], "to": "active"}],
        "SESSION_STOPPED": [{"from": "active", "to": "stopped"}],
        "SESSION_ENDED": [{"from": ["active", "stopped"], "to": "ended"}],
        "SESSION_SETTLED": [{"from": ["idle", "active", "stopped"], "to": "stopped"}],
    },
}
SESSION_EVENTS = tuple(_TABLE["events"])
#: The events that put a session to work: those the table moves to `active`.
WOKE = frozenset(event for event, rules in _TABLE["events"].items() if any(rule["to"] == "active" for rule in rules))
HARNESS = compile_document(_TABLE, Path("session-events"))
#: The session table as the page draws it, keyed by name like a board adapter's machines.
SESSION_MACHINES = {HARNESS.name: describe(HARNESS.machine)}


def ended_id(session: str, process: int | str) -> str:
    """The event id of a session's end: a clean exit and a watched process that name the same pid land once."""
    return f"session-ended:{session}:{process}"
