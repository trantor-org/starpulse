"""Which task each signal of a session belongs to.

The task a signal belongs to is the one the export's launch branch names under the board's `TaskKeys`, until a `claim`
signal (a command or a `Skill` call the `[analytics]` `claims` patterns matched) or a `branch` signal (a shell's `git
switch` or `git checkout`) names another. A launch branch that names no task leaves the session's first signals with none
to hold, so they belong to the first task a claim or branch signal names: a session's work before its claim is that
task's work, as the transcript-mined `session_signals` count it. A switch to a ref that names no task leaves the task as it
was, so `git checkout -- file` or a trip back to `main` does not drop a session's work from its slice.

A shell command's claim is read twice, so a change to `claims` reaches rows stored before it: the export is matched at
ingest, which stores a `claim` signal, and `session_signals` matches each stored shell command against the current patterns,
adding the claim a stored command names when the same tool result has no stored claim row (one claim per tool result).
A `Skill` call's claim is ingest-only: its arguments are never stored, so a claim pattern added later reaches only the
calls exported after it, and a stored command is matched as stored, after redaction.
"""

import re
from collections.abc import Iterator, Sequence
from math import inf

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.contracts.signals import Signal, claim_key, claimed

__all__ = ["attribution", "attributed", "session_signals"]


def _read_time_claims(ordered: list[Signal], claims: Sequence[re.Pattern[str]], keys: TaskKeys) -> list[Signal]:
    """`ordered` with a `claim` after each shell result whose stored command names a task and that has no stored claim
    row, as ingest would have minted it."""
    stored = {s.key for s in ordered if s.kind == "claim"}
    with_claims: list[Signal] = []
    for s in ordered:
        with_claims.append(s)
        if s.kind == "tool" and s.command and claim_key(s.key) not in stored:
            if (task := claimed(s.command, claims, keys)) is not None:
                with_claims.append(
                    Signal(s.harness, s.session, "claim", s.time, claim_key(s.key), s.branch, name=task, turn=s.turn)
                )
    return with_claims


def session_signals(
    signals: list[Signal], keys: TaskKeys | None = None, analytics: Analytics | None = None
) -> list[Signal]:
    """The signals of one session, oldest first. With `keys` and `analytics`, a stored shell command the current
    `claims` match is also a claim (see the module docstring)."""
    ordered = sorted(signals, key=lambda s: s.time)
    if keys is None or analytics is None or not analytics.claims:
        return ordered
    return _read_time_claims(ordered, analytics.claims, keys)


def attribution(
    ordered: list[Signal], keys: TaskKeys | None, carry: tuple[str | None, str | None] | None = None
) -> tuple[list[tuple[str | None, Signal]], str | None, str | None, float]:
    """Each signal of one session, oldest first, with the task it belongs to (see the module docstring), then the task
    in force, the first task named after the last signal and the time of the first signal that names a task (`-inf`
    when the stretch starts named, `inf` when none does). `carry`, the pair an earlier stretch of the session ended
    on, starts the stretch where that one stopped."""
    task, first = carry or (keys.for_branch(ordered[0].branch) if keys and ordered else None, None)
    tasks: list[str | None] = []
    for s in ordered:
        if s.kind == "claim" and keys and keys.matches(s.name):
            task = s.name
        elif s.kind == "branch" and keys and (named := keys.for_branch(s.name)) is not None:
            task = named
        tasks.append(task)
    # A task, once named, is never unnamed, so the signals still None are those before the first naming signal.
    first = first or next((t for t in tasks if t is not None), None)
    named_at = next((s.time for t, s in zip(tasks, ordered, strict=True) if t), inf)
    return [(t or first, s) for t, s in zip(tasks, ordered, strict=True)], task, first, named_at if None in tasks[:1] else -inf


def attributed(ordered: list[Signal], keys: TaskKeys | None) -> Iterator[tuple[str | None, Signal]]:
    """Each signal of one session, oldest first, with the task it belongs to (see the module docstring)."""
    yield from attribution(ordered, keys)[0]
