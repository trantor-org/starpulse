"""The Claude Code adapter: Claude Code's OpenTelemetry log export becomes events on the harness machine.

Point a session's log export at the receiver and every prompt, skill activation, tool result and reply
moves the session through the port's `events` map:

    CLAUDE_CODE_ENABLE_TELEMETRY=1 OTEL_LOGS_EXPORTER=otlp OTEL_EXPORTER_OTLP_PROTOCOL=http/json \\
    OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 OTEL_LOG_TOOL_DETAILS=1 \\
    OTEL_RESOURCE_ATTRIBUTES="vcs.ref.head.name=$(git branch --show-current)" claude

    python -m starpulse.runtime.claude_code [--host ADDR] [--port 4318] [--config FILE] [--key RE --branch RE --key-format FMT]

With `--redactor MODULE:FUNCTION`, each shell command's text is also kept on its tool signal, passed through that
function with every heredoc body replaced by its length and SHA-256; without one no command text is kept.

What a session's events say about its own work is read against the `[analytics]` table of that config: a prompt's
opening labels it `human` or `injected` (the text is read once and never stored), and a shell command or a `Skill`
call's arguments that match a `claims` pattern attributes the steps after it to that task.

Events are appended to the event log in the database `--config` names (default `starpulse.toml` in the working
directory), the store `starpulse serve` reads.

The export marks no turn end, and a reply is exported as each text answer lands, mid-turn included,
so every reply stops the session and its next tool call starts it again. A `Skill` tool result moves
nothing: the `skill_activated` record for the same call already did. The export names no working
directory or branch, so an event is keyed by the task the `vcs.ref.head.name` resource attribute's
branch names under the adapter's `TaskKeys`, else by the task the session last claimed, else by the session as a run.
A session resumed after the adapter restarted claims nothing anew, so its last claim is read once from the stored signals.

The adapter depends on nothing of a host project's: not its hooks, its `AGENTS.md` or its branch names.
"""

import argparse
import re
import socket
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.signals import CLAUDE_CODE, Signal
from starpulse.event_log import claude_sessions, events as machine_events
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import open_event_log
from starpulse.event_log.wake import StopEvent
from starpulse.harness_telemetry.adapters.outbound import step_seconds
from starpulse.harness_telemetry.model.claude_code_config import ClaudeCode
from starpulse.harness_telemetry.adapters.outbound.claude import ClaudeHarness
from starpulse.harness_telemetry.model.harness import HARNESS, ended_id
from starpulse.harness_telemetry.adapters.inbound.otlp import SETTLED, TOOL_RESULT, LogEvent, receiver
from starpulse.harness_telemetry.adapters.inbound.telemetry import ClaimUnreadable, redactor, signals, telemetry_log

ACTOR = "claude-code"
CLAUDE = ClaudeHarness()
DEFAULT_PORT = 4318


@dataclass(frozen=True)
class ClaudeCodeAdapter:
    """Maps Claude Code's log events onto `MachineEvent` dicts for `keys`' task scheme."""

    keys: TaskKeys
    clock: Callable[[], float] = lambda: datetime.now().timestamp()
    #: The turn each session last settled on: every `Stop` hook of one settle completes, and only the first counts.
    #: Any other event of the session that moves the harness clears it, so a turn a blocking `Stop` hook resumed settles again on its next stop.
    settled: dict[str, str] = field(default_factory=dict, compare=False)
    #: The task each session last claimed: a session whose export names no branch works it all the same.
    claimed: dict[str, str | None] = field(default_factory=dict, compare=False)
    #: The task a session claimed before this adapter started and when, read once per session that is readable:
    #: raises `ClaimUnreadable` when the store cannot be read, so the next lookup asks again.
    recall: Callable[[str], tuple[str, float] | None] = lambda _session: None
    #: When each session's noted claim was made: a batch that arrives late never replaces a newer claim.
    claimed_at: dict[str, float] = field(default_factory=dict, compare=False)
    #: Held while `claimed` and `claimed_at` change: the receiver serves each request on its own thread.
    lock: threading.Lock = field(default_factory=threading.Lock, compare=False)
    #: A session's terminal halt, its time and text, when its last turn is one: a settle that follows it ends the session.
    halted: Callable[[str], tuple[float, str] | None] = lambda _session: None

    def claim(self, found: Iterable[Signal]) -> None:
        """Note the task each `claim` signal in `found` names for its session, after the one it stored."""
        found = [signal for signal in found if signal.kind == "claim" and signal.name]
        for session in {signal.session for signal in found}:
            self._claimed(session)
        with self.lock:
            for signal in found:
                if signal.time >= self.claimed_at.get(signal.session, signal.time):
                    self.claimed[signal.session] = signal.name
                    self.claimed_at[signal.session] = signal.time

    def events(self, logs: list[LogEvent]) -> list[dict]:
        """The events `logs` move the harness machine by, in order."""
        found = []
        for log in logs:
            if _moves(log) and self._first(log):
                found.append(self._event(log))
                halt = self.halted(log.session) if log.kind == SETTLED else None
                if halt and (log.time is None or halt[0] <= log.time):  # a settle older than the halt is another turn's
                    found.append(self._ended(log, halt[0]))
        return found

    def _first(self, log: LogEvent) -> bool:
        if log.kind != SETTLED or not log.prompt:
            self.settled.pop(log.session, None)
            return True
        first = self.settled.get(log.session) != log.prompt
        self.settled[log.session] = log.prompt
        return first

    def _claimed(self, session: str) -> str | None:
        if session not in self.claimed:
            try:
                recalled = self.recall(session)
            except ClaimUnreadable:
                return None
            with self.lock:
                if recalled and recalled[1] > self.claimed_at.get(session, float("-inf")):
                    self.claimed[session], self.claimed_at[session] = recalled
                else:
                    self.claimed.setdefault(session, None)
        return self.claimed[session]

    def _ended(self, log: LogEvent, at: float) -> dict:
        return {
            **self._event(log, "SESSION_ENDED"),
            "event_id": ended_id(log.session, f"halt-{at}"),
            "session": log.session,
        }

    def _event(self, log: LogEvent, name: str | None = None) -> dict:
        task = self.keys.for_branch(log.branch) or self._claimed(log.session)
        return {
            "machine": HARNESS.name,
            "event": name or CLAUDE.events[log.kind],
            "task": task,
            "run": None if task else log.session,
            "actor": ACTOR,
            "time": self.clock() if log.time is None else log.time,
        }


def _moves(log: LogEvent) -> bool:
    return log.kind in CLAUDE.events and not (log.kind == TOOL_RESULT and log.tool_name == "Skill")


def handler(
    adapter: ClaudeCodeAdapter,
    publish: Callable[[dict], object],
    telemetry: Callable[[dict], object] | None = None,
    metrics: tuple[str, Callable[[], bytes]] | None = None,
) -> type[BaseHTTPRequestHandler]:
    """An OTLP/HTTP logs handler that publishes each event an export maps to, hands `telemetry` each export and
    serves `metrics` (a content type and a renderer) at `GET /metrics`."""

    def ingest(logs: list[LogEvent]) -> None:
        for event in adapter.events(logs):
            publish(event)

    return receiver(ingest, telemetry, metrics)


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
            event_id=event.get("event_id"),
            log=log,
        )

    return publish


def bind(
    settings: ClaudeCode, config: Any, log: EventLog, listening: socket.socket | None = None
) -> ThreadingHTTPServer:
    """The receiver listening on `listening`, the socket `serve` keeps open across a worker replacement, else on
    `settings`' address, appending to `log`. Raises `ValueError` for a redactor that cannot be loaded and `OSError` for
    an address that cannot be bound."""
    keys = TaskKeys(key=re.compile(settings.key), branch=re.compile(settings.branch), key_format=settings.key_format)
    redact = redactor(settings.redactor) if settings.redactor else None
    telemetry = telemetry_log(log, keys, config.analytics)

    transcripts = Path(config.board.get("transcripts", claude_sessions.DEFAULT_TRANSCRIPTS)).expanduser()
    adapter = ClaudeCodeAdapter(
        keys,
        recall=lambda session: telemetry.last_claim(CLAUDE_CODE, session),
        halted=claude_sessions.terminal_halt(partial(claude_sessions.last_turn, transcripts)),
    )

    publish = publisher(log)

    def publish_event(event: dict) -> None:
        publish(event)
        if event["event"] == "SESSION_ENDED":
            telemetry.close(CLAUDE_CODE, event["session"])

    def publish_signals(found: list[Signal]) -> None:
        adapter.claim(found)
        step_seconds.observe(found)
        telemetry.publish(found)

    receiver = handler(
        adapter,
        publish_event,
        lambda payload: publish_signals(signals(payload, redact, analytics=config.analytics, keys=keys)),
        (step_seconds.CONTENT_TYPE, step_seconds.exposition),
    )
    if listening is None:
        return ThreadingHTTPServer((settings.host, settings.port), receiver)
    server = ThreadingHTTPServer(listening.getsockname()[:2], receiver, bind_and_activate=False)
    server.socket.close()  # closing the held socket ends this process's copy; a delivery before the next accept queues
    server.socket = listening
    return server


def start(
    config: Any, log: EventLog, stop: StopEvent, listening: socket.socket | None = None
) -> Callable[[], None]:
    """The `claude-code` context: serve `[claude_code]` on threads, on `listening` when `serve` holds the socket, until
    `stop` is set, which closes the listener.

    Raises `ValueError` without the table or with a redactor that cannot be loaded, and `OSError` when the address is
    taken, which the `contexts` process retries with a backoff. Returns the context's reload, which has nothing to
    re-read: the table is a restart block."""
    if config.claude_code is None:
        raise ValueError("the claude-code context needs a [claude_code] table")
    server = bind(config.claude_code, config, log, listening)

    def close() -> None:
        stop.wait()
        server.shutdown()
        server.server_close()

    threading.Thread(target=server.serve_forever, name="claude-code-receiver", daemon=True).start()
    threading.Thread(target=close, name="claude-code-close", daemon=True).start()
    return lambda: None


def main(
    argv: list[str] | None = None,
    *,
    discover: Callable[[Path | None], Path | None],
    load: Callable[[Path | None], Any],
) -> None:
    """Serve the receiver; `discover` and `load` read the root config, which the runtime owns and passes in."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--config", type=Path, help="the TOML config whose database holds the event log")
    parser.add_argument("--key", default=r"TASK-\d+", help="a whole task key")
    parser.add_argument(
        "--branch", default=r"(?i)(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", help="group 1 names the key"
    )
    parser.add_argument("--key-format", default="TASK-{}", help="wraps the branch's group 1 into the key")
    parser.add_argument(
        "--redactor",
        metavar="MODULE:FUNCTION",
        help="the filter a shell command's text passes through before it is stored; without one none is stored",
    )
    args = parser.parse_args(argv)
    settings = ClaudeCode(args.host, args.port, args.key, args.branch, args.key_format, args.redactor)

    try:
        path = discover(args.config)
        config = load(path)
        log = open_event_log(config.database_url, path)
    except (OSError, ValueError) as exc:
        parser.error(f"{args.config or 'starpulse.toml'}: {exc}")

    try:
        server = bind(settings, config, log)
    except ValueError as exc:
        parser.error(str(exc))

    print(f"claude code adapter on {args.host}:{args.port}", flush=True)
    server.serve_forever()
