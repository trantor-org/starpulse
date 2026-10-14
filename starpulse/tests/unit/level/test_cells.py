"""The cell report: median steps per clean completion per kind x size cell, read from session and slice health."""

import re
from itertools import count

import pytest

from starpulse._internal.config.analytics import Analytics
from starpulse._internal.harnesses.telemetry import CLAUDE_CODE, CODEX, Signal
from starpulse._internal.level.cells import cell_report, transition_cost
from starpulse._internal.level.sessions import session_health, slice_health
from starpulse.contracts.adapters import TaskKeys

KEYS = TaskKeys(
    key=re.compile(r"TASK-\d+"),
    branch=re.compile(r"(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", re.IGNORECASE),
    key_format="TASK-{}",
)
ANALYTICS = Analytics(completion_skill="completing-tasks")
_N = count()


def sig(kind: str, at: float, session: str, harness: str = CLAUDE_CODE, **fields: object) -> Signal:
    return Signal(harness, session, kind, at, f"{harness}:{session}:{next(_N)}", **fields)  # type: ignore[arg-type]


def completion(
    number: int, steps: int, end: float, *, steered: int = 0, side: int = 0, harness: str = CLAUDE_CODE
) -> list[Signal]:
    """One session's completed work on TASK-`number`: `steps` main requests (the first followed by an edit), `side`
    subagent requests and `steered` human prompts after the first, ending at `end`."""
    s = f"s{number}"
    branch = f"claude/task-{number}-x"
    begin = end - 1000
    found = [sig("prompt", begin, s, harness, branch=branch, turn="p1", detail="human")]
    for at in range(steps):
        found.append(sig("request", begin + 1 + at, s, harness, branch=branch, model="m", turn="p1"))
        if at == 0:
            found.append(sig("tool", begin + 1.5, s, harness, branch=branch, name="Edit", turn="p1"))
    found += [
        sig("request", begin + 3 + at / 100, s, harness, branch=branch, model="m", origin="side", turn="p1")
        for at in range(side)
    ]
    found += [
        sig("skill", end - 10, s, harness, branch=branch, name="completing-tasks", turn="p1"),
        sig("deliver", end - 9, s, harness, branch=branch, turn="p1"),
        sig("reply", end - 8, s, harness, branch=branch, turn="p1"),
    ]
    for at in range(steered):
        found += [
            sig("prompt", end - 7 + at * 2, s, harness, branch=branch, turn=f"q{at}", detail="human"),
            sig("reply", end - 6 + at * 2, s, harness, branch=branch, turn=f"q{at}"),
        ]
    return found


def report(*found: list[Signal], labels: dict[str, list[str]]) -> list[dict]:
    rows = session_health([s for group in found for s in group], KEYS, ANALYTICS)
    return cell_report(slice_health(rows), {task: {"labels": tags} for task, tags in labels.items()})


EXECUTE_8 = ["kind-execute", "size-8"]
EXECUTE_3 = ["kind-execute", "size-3"]


def test_a_cell_of_five_clean_completions_reports_its_holdout_median_n_clean_rate_and_blind_spot_medians() -> None:
    cell = [completion(n, steps=10 * n, end=10_000 + n, side=int(n == 5)) for n in range(1, 6)]
    steered = completion(6, steps=7, end=10_006, steered=2)  # a completion, but not clean
    uncaptured = completion(7, steps=1, end=10_007, harness=CODEX)
    four = [completion(n, steps=5, end=20_000 + n) for n in range(11, 15)]
    labels = {f"TASK-{n}": EXECUTE_8 for n in [*range(1, 8)]} | {f"TASK-{n}": EXECUTE_3 for n in range(11, 15)}

    rows = report(*cell, steered, uncaptured, *four, labels=labels)

    assert rows == [
        {
            "kind": "execute",
            "size": 8,
            "n": 5,
            "completions": 6,
            "clean_rate": pytest.approx(5 / 6),
            "holdout": 1,
            "median_steps": 51,  # TASK-5's 50 main requests and its one subagent request
            "median_operator_prompts": 1,  # the latest two completions: the steered one's 2 and TASK-5's 0
            "median_steps_before_edit": 1,
        }
    ]


def test_the_holdout_is_the_latest_fifth_of_the_cells_clean_completions_by_end_time() -> None:
    older = [completion(n, steps=10, end=1_000 * n) for n in range(1, 9)]
    latest = [completion(10, steps=100, end=20_000), completion(9, steps=200, end=15_000)]
    labels = {f"TASK-{n}": EXECUTE_3 for n in range(1, 11)}

    rows = report(*latest, *reversed(older), labels=labels)  # fed newest first

    assert [(r["n"], r["holdout"], r["median_steps"]) for r in rows] == [(10, 2, 150)]


def test_a_transition_counts_its_subagent_steps_and_its_failed_refused_and_repeated_calls_as_wasted() -> None:
    branch = "claude/task-1-x"

    def at(kind: str, time: float, **fields: object) -> Signal:
        return sig(kind, time, "s1", branch=branch, **fields)

    def req(time: float, *, input: int = 0, cache_read: int = 0, cache_write: int = 0, **fields: object) -> Signal:
        return at(
            "request",
            time,
            model="m",
            seconds=2,
            input=input,
            cache_read=cache_read,
            cache_write=cache_write,
            **fields,
        )

    found = [
        at("prompt", 0, turn="p1", detail="human"),
        req(10, input=100, cache_read=900),
        at("skill", 10.2, name="work"),
        at("tool", 11, name="Bash", command="ls", seconds=0.5),
        req(20, input=100, cache_read=2800, cache_write=100),
        at("tool", 21, name="Bash", command="make test", ok=False, seconds=0.5),  # failed
        req(30, input=2000),
        at("decision", 31, name="Bash", ok=False, detail="hook"),  # refused by a hook: no result follows
        req(40, input=500),
        at("tool", 41, name="Bash", command="make test", seconds=0.5),  # repeats the command before it
        req(50, input=700, origin="side", agent="Explore"),  # a subagent's step is the task's
        at("tool", 51, name="Read", seconds=0.5),
        at("reply", 52, turn="p1"),
    ]
    other = [
        sig("request", 10, "s2", branch="claude/task-2-x", model="m", seconds=1, input=50),
        sig("skill", 10.1, "s2", branch="claude/task-2-x", name="work"),
    ]
    unlabelled = [sig("request", 10, "s3", branch="claude/task-3-x", model="m", seconds=1)]
    tasks = {"TASK-1": {"labels": EXECUTE_8}, "TASK-2": {"labels": EXECUTE_3}}

    rows = transition_cost([*found, *other, *unlabelled], KEYS, tasks)

    assert rows == [
        {
            "kind": "execute",
            "size": 3,
            "skill": "work",
            "tasks": 1,
            "steps": 1,
            "side_steps": 0,
            "wasted_steps": 0,
            "wasted_rate": 0.0,
            "agent_s": pytest.approx(1.0),
            "peak_context": 50,
        },
        {
            "kind": "execute",
            "size": 8,
            "skill": "work",
            "tasks": 1,
            "steps": 5,
            "side_steps": 1,
            "wasted_steps": 3,
            "wasted_rate": pytest.approx(0.6),
            "agent_s": pytest.approx(5 * 2 + 4 * 0.5),
            "peak_context": 3000,
        },
    ]


def test_the_operator_prompt_median_is_over_the_latest_fifth_of_all_completions_not_only_clean_ones() -> None:
    clean = [completion(n, steps=10, end=1_000 * n) for n in range(1, 6)]
    steered = [completion(6, steps=10, end=6_000, steered=3), completion(7, steps=10, end=7_000, steered=1)]
    labels = {f"TASK-{n}": EXECUTE_3 for n in range(1, 8)}

    (row,) = report(*clean, *steered, labels=labels)

    assert (row["n"], row["completions"], row["holdout"]) == (5, 7, 1)
    assert row["median_operator_prompts"] == 2  # the latest two completions (ceil of 7/5), both steered
