"""The per-session folds and their combines give what the whole-list entry points gave before the split.

`golden/folds.json` holds the outputs of the entry points as they were before the folds were split out, over `history()`;
each test composes a view from per-session folds plus its combine and compares it with the golden, and every fold's
result must survive a `json.dumps`/`json.loads` unchanged. Seconds are multiples of a quarter, so a sum comes out the
same whatever the order it is added in.
"""

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics, MachineStage, SkillMachine
from starpulse.contracts.signals import CLAUDE_CODE, CODEX, Signal
from starpulse.flow_metrics.model import cells, flow, session_health, steps

GOLDEN = Path(__file__).parent / "golden" / "folds.json"
KEYS = TaskKeys(
    key=re.compile(r"TASK-\d+"),
    branch=re.compile(r"(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", re.IGNORECASE),
    key_format="TASK-{}",
)
ANALYTICS = Analytics(
    completion_skill="completing-tasks",
    stop_activities=frozenset({"Skill"}),
    skill_machines=(
        SkillMachine(
            "work",
            (
                MachineStage("read", frozenset({"read"})),
                MachineStage("edit", frozenset({"edit"})),
                MachineStage("test", frozenset({"test"}), ok=True),
            ),
        ),
    ),
)
BANDS = [(3, 20, 5.0), (8, 60, 30.0)]
WINDOW_START = 1500.0
SINCE = 2500.0
TASKS = {
    f"TASK-{n}": {"labels": ["kind-execute", "size-8"], "milestone": "m-1"}
    for n in (*range(1, 10), *range(11, 17), *range(21, 27))
}
TASKS["TASK-10"] = {"labels": ["kind-execute", "size-3"], "milestone": "m-1"}


def sig(kind: str, at: float, session: str, **fields: Any) -> Signal:
    return Signal(CLAUDE_CODE, session, kind, at, f"{session}:{kind}:{at}:{fields.get('name', '')}", **fields)


def work(session: str, number: int, begin: float, activities: list[str], *, skill: bool) -> list[Signal]:
    """A session's requests on TASK-`number`, each followed by the tool call that made an activity (`!` failed)."""
    branch = f"claude/task-{number}-x"
    found = [sig("prompt", begin, session, branch=branch, turn=f"{session}-p", detail="human")]
    for at, activity in enumerate(activities):
        t = begin + 5 + at * 10
        found.append(
            sig("request", t, session, branch=branch, model="m", seconds=1.25, input=100 + at, turn=f"{session}-p")
        )
        if skill and at == 0:
            found.append(sig("skill", t + 0.1, session, branch=branch, name="work", turn=f"{session}-p"))
        found.append(
            sig(
                "tool",
                t + 1,
                session,
                branch=branch,
                name="Bash" if activity != "edit" else "Edit",
                activities=(activity.rstrip("!"),),
                command="make check" if activity.startswith("fix") else None,
                ok=not activity.endswith("!"),
                seconds=0.75,
                turn=f"{session}-p",
            )
        )
    return found


def finish(session: str, number: int, end: float) -> list[Signal]:
    branch = f"claude/task-{number}-x"
    return [
        sig("skill", end - 3, session, branch=branch, name="completing-tasks", turn=f"{session}-p"),
        sig("deliver", end - 2, session, branch=branch, turn=f"{session}-p"),
        sig("reply", end - 1, session, branch=branch, turn=f"{session}-p"),
    ]


def stretch(number: int, begin: float) -> list[Signal]:
    """A long run under no skill: ten reads, a choice of `edit` or `plan`, a test or a lint, then nine fixes."""
    activities = ["read"] * 10 + ["edit" if number % 3 else "plan", "test" if number % 2 else "lint"] + ["fix"] * 9
    return work(f"s{number}", number, begin, activities, skill=False)


def history() -> list[Signal]:
    """Single-session tasks 1-7 (3 steered), TASK-8 worked by two sessions, TASK-9 by a session that began before the
    window, long ungoverned stretches in the weeks either side of `SINCE`, and a Codex session."""
    found: list[Signal] = []
    for n in range(1, 8):
        base = n * 1000.0 + 600
        tail = ["test" if n % 2 else "lint", "fix", "fix", "test!"] if n != 5 else ["test"]
        found += work(f"a{n}", n, base, ["read", "edit", *tail], skill=True)
        if n == 3:  # a human steers after the claim: complete, not clean
            found += [sig("prompt", base + 90, f"a{n}", branch=f"claude/task-{n}-x", turn="a3-q", detail="human")]
        found += [sig("request", base + 7, f"a{n}", branch=f"claude/task-{n}-x", model="m", origin="side", seconds=0.5)]
        found += finish(f"a{n}", n, base + 300)
    found += work("a8", 8, 8600.0, ["read", "edit"], skill=True) + work("b8", 8, 8800.0, ["test"], skill=False)
    found += finish("b8", 8, 8900.0)
    # one session that began before the window: TASK-9 from 1100, read-only until the window opens at 1500
    found += work("long", 9, 1100.0, ["read"] * 30 + ["edit", "test"], skill=True) + finish("long", 9, 2000.0)
    found += [s for n in range(11, 17) for s in stretch(n, 3000.0 + n * 400)]  # this week
    found += [s for n in range(21, 27) for s in stretch(n, 1520.0 + (n - 21) * 40)]  # the week before
    found += [
        Signal(CODEX, "cx", "request", 3000.0, "cx:1", branch="codex/task-10-x", model="gpt", seconds=1.0),
        Signal(CODEX, "cx", "tool", 3001.0, "cx:2", branch="codex/task-10-x", name="shell", ok=True),
    ]
    return [s for s in found if s.time >= WINDOW_START]


def by_session(found: list[Signal]) -> list[list[Signal]]:
    return session_health.by_session(found)


def combined() -> dict[str, Callable[[], Any]]:
    """Each view, composed from per-session folds and its combine."""
    found = history()
    groups = by_session(found)

    def health() -> list[dict[str, Any]]:
        return session_health.combine_health([session_health.fold_health(g, KEYS, ANALYTICS) for g in groups])

    def runs() -> list[list[dict[str, Any]]]:
        return [flow.fold_runs(g, KEYS, ANALYTICS) for g in groups]

    return {
        "session_health": health,
        "slice_health": lambda: session_health.slice_health(health()),
        "session_steps": lambda: steps.combine_steps([steps.fold_steps(g, KEYS, ANALYTICS) for g in groups]),
        "transition_cost": lambda: cells.combine_cost([cells.fold_cost(g, KEYS, ANALYTICS) for g in groups], TASKS),
        "cell_report": lambda: cells.cell_report(session_health.slice_health(health()), TASKS),
        "estimate_report": lambda: cells.estimate_report(session_health.slice_health(health()), TASKS, BANDS),
        "directly_follows": lambda: flow.combine_edges(runs(), TASKS, ANALYTICS),
        "sub_stages": lambda: flow.combine_stages(runs(), TASKS, ANALYTICS, since=SINCE),
        "fast_slow_diff": lambda: flow.combine_diff(runs(), health(), TASKS, ANALYTICS),
        "cost_to_go": lambda: flow.combine_cost_to_go(runs(), health(), TASKS, ANALYTICS),
    }


def whole_list() -> dict[str, list[dict[str, Any]]]:
    """Each view from its whole-list entry point."""
    found = history()
    sessions = session_health.session_health(found, KEYS, ANALYTICS)
    return {
        "session_health": sessions,
        "slice_health": session_health.slice_health(sessions),
        "session_steps": steps.session_steps(found, KEYS, ANALYTICS),
        "transition_cost": cells.transition_cost(found, KEYS, TASKS, ANALYTICS),
        "cell_report": cells.cell_report(session_health.slice_health(sessions), TASKS),
        "estimate_report": cells.estimate_report(session_health.slice_health(sessions), TASKS, BANDS),
        "directly_follows": flow.directly_follows(found, KEYS, TASKS, ANALYTICS),
        "sub_stages": flow.sub_stages(found, KEYS, TASKS, ANALYTICS, since=SINCE),
        "fast_slow_diff": flow.fast_slow_diff(found, KEYS, TASKS, ANALYTICS),
        "cost_to_go": flow.cost_to_go(found, KEYS, TASKS, ANALYTICS),
    }


def golden() -> dict[str, list[dict[str, Any]]]:
    return json.loads(GOLDEN.read_text())


VIEWS = list(golden())


def test_the_golden_holds_a_row_for_every_view() -> None:
    held = golden()

    assert all(held[view] for view in VIEWS)
    assert {"session_health", "session_steps", "transition_cost", "cell_report", "directly_follows"} <= set(held)
    assert {"sub_stages", "fast_slow_diff", "cost_to_go"} <= set(held)


@pytest.mark.parametrize("view", VIEWS)
def test_per_session_folds_plus_the_combine_give_what_the_whole_list_gave_before_the_split(view: str) -> None:
    assert json.loads(json.dumps(combined()[view]())) == golden()[view]


@pytest.mark.parametrize("view", VIEWS)
def test_the_whole_list_entry_point_is_unchanged(view: str) -> None:
    assert json.loads(json.dumps(whole_list()[view])) == golden()[view]


def folds() -> dict[str, Callable[[list[Signal]], Any]]:
    return {
        "fold_health": lambda g: session_health.fold_health(g, KEYS, ANALYTICS),
        "fold_steps": lambda g: steps.fold_steps(g, KEYS, ANALYTICS),
        "fold_cost": lambda g: cells.fold_cost(g, KEYS, ANALYTICS),
        "fold_runs": lambda g: flow.fold_runs(g, KEYS, ANALYTICS),
    }


@pytest.mark.parametrize("fold", list(folds()))
def test_each_fold_result_round_trips_json_unchanged(fold: str) -> None:
    results = [folds()[fold](group) for group in by_session(history())]

    assert any(results)
    assert all(json.loads(json.dumps(result)) == result for result in results)
