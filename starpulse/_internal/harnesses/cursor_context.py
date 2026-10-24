"""Context use of live Cursor sessions, read from the agent's pane footer."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from starpulse._internal.config.config import discover, load
from starpulse._internal.eventlog.history import open_event_log
from starpulse._internal.harnesses.session_start import starter
from starpulse.contracts.adapters import StartFailedError
from starpulse.event_log.event_log import EventLog

#: The context percent the footer ends on (`Auto  60.3%`); a percent mid-line is output, not the footer.
_FOOTER = re.compile(r"\b(\d{1,3}(?:\.\d+)?)%\s*$")


def context_tokens(pane: str, window: int) -> int | None:
    """The tokens of context a Cursor pane's footer reports against a model window of `window` tokens.

    The last line that ends on a percent is the footer; a pane with none has no reading.
    """
    for line in reversed(pane.splitlines()):
        if match := _FOOTER.search(line):
            return round(float(match[1]) / 100 * window)
    return None


#: The stream each reading is appended to: `{session, task, tokens, window}`, one row per session per minute. Private
#: like `telemetry:signals`: no `EVENT_STREAMS` entry, no consumer tails it.
CONTEXT_STREAM = "cursor:context"
_STALE = 3  # a wrap-up request older than this many deadlines belongs to a session since gone


class Panes(Protocol):
    """The live Cursor task sessions' panes, behind the seam a test replaces with plain text."""

    def sessions(self) -> list[str]: ...

    def read(self, name: str) -> str: ...

    def send(self, name: str, text: str) -> None: ...

    def kill(self, name: str) -> None: ...


def reset_over_limit(
    panes: Panes,
    log: EventLog,
    start: Callable[..., str],
    *,
    limit: int,
    window: int,
    wrapup: str,
    wrapup_s: float,
    now: float,
) -> list[str]:
    """Record each Cursor session's context tokens and ask each one over `limit` to wrap up, then restart it."""
    acted: list[str] = []
    failed: list[str] = []
    for name in panes.sessions():
        pane = panes.read(name)
        task = name.upper()
        tokens = context_tokens(pane, window)
        if tokens is None:
            continue
        fields = {"session": name, "task": task, "tokens": tokens, "window": window}
        log._append(CONTEXT_STREAM, fields, event_id=f"{name}:{int(now // 60)}")
        key = f"cursor-context:{name}"
        if tokens < limit:
            log.delete_setting(key)
            continue
        digest = hashlib.sha256(pane.encode()).hexdigest()
        asked_at = log.setting_updated_at(key)
        if asked_at is None or now - asked_at > _STALE * wrapup_s:
            panes.send(name, wrapup)
            log.set_setting(key, {"digest": digest}, updated_at=now)
            acted.append(f"{task}: asked to wrap up at {tokens} tokens")
        elif (log.setting(key) or {}).get("digest") == digest or now - asked_at >= wrapup_s:
            log.delete_setting(key)
            panes.kill(name)
            try:
                start(task, harness="cursor", mode="interactive")
            except StartFailedError as exc:
                failed.append(f"{task}: {exc}")
                continue
            acted.append(f"{task}: restarted fresh at {tokens} tokens")
        else:
            log.set_setting(key, {"digest": digest}, updated_at=asked_at)
    if failed:
        raise StartFailedError(f"could not restart {'; '.join(failed)}")
    return acted


_CURSOR_AGENTS = {"cursor-agent", "agent"}
_TASK_SESSION = re.compile(r"task-\d+")

#: What a session is asked once it is over the limit; `Start TASK-N` on the fresh session then reads the working doc.
WRAPUP = (
    "[context-reset] This session's context is over its limit and will be restarted fresh on this task. "
    "Now: update the task's working doc (Current state, Decisions, Open questions, Next step), add a one-line "
    "task comment, and commit any work in progress. Then stop."
)


def cursor_task_sessions(panes: str, processes: str) -> list[str]:
    """The `task-N` tmux sessions running Cursor's agent: `panes` is `session pid` lines, `processes` `ps -eo pid,ppid,args`.

    A session is Cursor's when a process below its pane starts as `cursor-agent` or `agent` (the launcher execs node
    under its own `$0`, so argv0 names it); a mention of the name in another command's arguments is not one.
    """
    children: dict[int, list[int]] = {}
    cursor: set[int] = set()
    for line in processes.splitlines()[1:]:
        fields = line.split(None, 2)
        if len(fields) < 3 or not (fields[0].isdigit() and fields[1].isdigit()):
            continue
        pid, parent = int(fields[0]), int(fields[1])
        children.setdefault(parent, []).append(pid)
        if fields[2].split()[0].rsplit("/", 1)[-1] in _CURSOR_AGENTS:
            cursor.add(pid)
    found: list[str] = []
    for line in panes.splitlines():
        name, _, pid = line.partition(" ")
        if _TASK_SESSION.fullmatch(name) and pid.strip().isdigit() and _runs_cursor(int(pid), children, cursor):
            found.append(name)
    return found


def _runs_cursor(root: int, children: dict[int, list[int]], cursor: set[int]) -> bool:
    queue, seen = [root], set()
    while queue:
        pid = queue.pop()
        if pid in cursor:
            return True
        if pid not in seen:
            seen.add(pid)
            queue.extend(children.get(pid, ()))
    return False


class TmuxPanes:  # pragma: no mutate block — process boundary
    """`Panes` over the host's tmux: the `task-N` sessions whose pane runs Cursor's agent."""

    def sessions(self) -> list[str]:
        listing = _run(["tmux", "list-panes", "-a", "-F", "#{session_name} #{pane_pid}"])
        return cursor_task_sessions(listing, _run(["ps", "-eo", "pid,ppid,args"])) if listing else []

    def read(self, name: str) -> str:
        return _run(["tmux", "capture-pane", "-p", "-t", f"={name}:"])

    def send(self, name: str, text: str) -> None:
        _run(["tmux", "send-keys", "-t", f"={name}:", "-l", text])
        _run(["tmux", "send-keys", "-t", f"={name}:", "Enter"])

    def kill(self, name: str) -> None:
        _run(["tmux", "kill-session", "-t", f"={name}"])


def _run(command: list[str]) -> str:  # pragma: no mutate block — process boundary
    done = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    return done.stdout if done.returncode == 0 else ""


def main(argv: list[str] | None = None) -> None:  # pragma: no mutate block — process boundary
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--config", type=Path, help="the TOML config naming the event log, limit and session starter")
    args = parser.parse_args(argv)
    try:
        path = discover(args.config)
        config, log = load(path), open_event_log(args.config)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    start = starter(config.session_start_url)
    if start is None:
        parser.error("no session_start_url is configured, so a session cannot be restarted")
    limits = config.cursor_context
    acted = reset_over_limit(
        TmuxPanes(),
        log,
        start,
        limit=limits.limit_tokens,
        window=limits.window_tokens,
        wrapup=WRAPUP,
        wrapup_s=limits.wrapup_s,
        now=time.time(),
    )
    print(f"cursor_context: {len(acted)} session(s) acted on", flush=True)
    for line in acted:
        print(f"cursor_context: {line}", flush=True)


if __name__ == "__main__":
    main()
