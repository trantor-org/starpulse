"""The Claude Code adapter: Claude Code's OpenTelemetry log export becomes events on the harness machine.

Point a session's log export at the receiver and every prompt, skill activation, tool result and reply
moves the session through the machine's `bindings`:

    CLAUDE_CODE_ENABLE_TELEMETRY=1 OTEL_LOGS_EXPORTER=otlp OTEL_EXPORTER_OTLP_PROTOCOL=http/json \\
    OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 OTEL_LOG_TOOL_DETAILS=1 \\
    OTEL_RESOURCE_ATTRIBUTES="vcs.ref.head.name=$(git branch --show-current)" claude

    python -m starpulse.claude_code [--host ADDR] [--port 4318] [--config FILE] [--key RE --branch RE --key-format FMT]

Events are appended to the event log in the database `--config` names (default `starpulse.toml` in the working
directory), the store `starpulse serve` reads.

The export marks no turn end, and a reply is exported as each text answer lands, mid-turn included,
so every reply stops the session and its next tool call starts it again. A `Skill` tool result moves
nothing: the `skill_activated` record for the same call already did. The export names no working
directory or branch, so an event is keyed by the task the `vcs.ref.head.name` resource attribute's
branch names under the adapter's `TaskKeys`, else by the session as a run.

The adapter depends on nothing of trantor's: not its hooks, its `AGENTS.md` or its branch names.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from starpulse._internal.adapters.harnesses.harness import HARNESS
from starpulse._internal.adapters.harnesses.otlp import TOOL_RESULT, LogEvent, receiver
from starpulse.contracts.adapters import TaskKeys
from starpulse._internal.store import events as machine_events
from starpulse._internal.store.event_log import EventLog
from starpulse._internal.store.history import open_event_log

ACTOR = "claude-code"
DEFAULT_PORT = 4318


@dataclass(frozen=True)
class ClaudeCodeAdapter:
    """Maps Claude Code's log events onto `MachineEvent` dicts for `keys`' task scheme."""

    keys: TaskKeys
    clock: Callable[[], float] = lambda: datetime.now().timestamp()

    def events(self, logs: list[LogEvent]) -> list[dict]:
        """The events `logs` move the harness machine by, in order."""
        return [self._event(log) for log in logs if _moves(log)]

    def _event(self, log: LogEvent) -> dict:
        task = self.keys.for_branch(log.branch)
        return {
            "machine": HARNESS.name,
            "event": HARNESS.bindings[log.kind],
            "task": task,
            "run": None if task else log.session,
            "actor": ACTOR,
            "time": self.clock() if log.time is None else log.time,
        }


def _moves(log: LogEvent) -> bool:
    return log.kind in HARNESS.bindings and not (log.kind == TOOL_RESULT and log.tool_name == "Skill")


def handler(adapter: ClaudeCodeAdapter, publish: Callable[[dict], object]) -> type[BaseHTTPRequestHandler]:
    """An OTLP/HTTP logs handler that publishes each event an export maps to."""

    def ingest(logs: list[LogEvent]) -> None:
        for event in adapter.events(logs):
            publish(event)

    return receiver(ingest)


def publisher(log: EventLog) -> Callable[[dict], int | None]:
    """Appends each event the adapter maps to `log`, fail-open."""

    def publish(event: dict) -> int | None:
        return machine_events.publish(
            event["machine"],
            event["event"],
            actor=event["actor"],
            task=event["task"],
            run=event["run"],
            now=event["time"],
            log=log,
        )

    return publish


def main(argv: list[str] | None = None) -> None:  # pragma: no mutate block — serve_forever process boundary
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--config", type=Path, help="the TOML config whose database holds the event log")
    parser.add_argument("--key", default=r"TASK-\d+", help="a whole task key")
    parser.add_argument(
        "--branch", default=r"(?i)(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", help="group 1 names the key"
    )
    parser.add_argument("--key-format", default="TASK-{}", help="wraps the branch's group 1 into the key")
    args = parser.parse_args(argv)
    keys = TaskKeys(key=re.compile(args.key), branch=re.compile(args.branch), key_format=args.key_format)

    try:
        log = open_event_log(args.config)
    except (OSError, ValueError) as exc:
        parser.error(f"{args.config or 'starpulse.toml'}: {exc}")

    print(f"claude code adapter on {args.host}:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), handler(ClaudeCodeAdapter(keys), publisher(log))).serve_forever()


if __name__ == "__main__":
    main()
