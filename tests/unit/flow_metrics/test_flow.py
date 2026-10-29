"""The branching directly-follows graph, the mined sub-stages and the fast-against-slow diff, read from the steps ledger."""

import re
from itertools import count

import pytest
from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics, MachineStage, SkillMachine
from starpulse.flow_metrics.model.flow import cost_to_go, directly_follows, fast_slow_diff, sub_stages
from starpulse.harness_telemetry.adapters.inbound.telemetry import CLAUDE_CODE, Signal

KEYS = TaskKeys(
    key=re.compile(r"TASK-\d+"),
    branch=re.compile(r"(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", re.IGNORECASE),
    key_format="TASK-{}",
)
ANALYTICS = Analytics(completion_skill="completing-tasks", stop_activities=frozenset({"Skill"}))
EXECUTE_8 = {"labels": ["kind-execute", "size-8"]}
_N = count()


def sig(kind: str, at: float, session: str, **fields: object) -> Signal:
    return Signal(CLAUDE_CODE, session, kind, at, f"{session}:{next(_N)}", **fields)  # type: ignore[arg-type]


def run(number: int, *calls: str, skill: str | None = "work", start: float = 0.0) -> list[Signal]:
    """One session on TASK-`number`: one model request per call in `calls`, each followed by the tool call that
    performed that activity (a call ending in `!` failed). `skill` is loaded by the first request."""
    s, branch = f"s{number}", f"claude/task-{number}-x"
    found: list[Signal] = []
    for at, activity in enumerate(calls):
        t = start + number * 1000 + at * 10
        found.append(sig("request", t, s, branch=branch, model="m"))
        if at == 0 and skill:
            found.append(sig("skill", t + 0.1, s, branch=branch, name=skill))
        found.append(
            sig(
                "tool",
                t + 1,
                s,
                branch=branch,
                name="Bash",
                activities=(activity.rstrip("!"),),
                ok=not activity.endswith("!"),
            )
        )
    return found


def test_the_graph_lists_each_activity_edge_with_its_run_count_and_marks_the_edges_leaving_a_judgement_cut() -> None:
    found = [s for n in range(1, 7) for s in run(n, "read", "edit", "test" if n <= 3 else "lint")]
    found += run(7, "read", "edit", "test", skill="other")  # another transition
    tasks = {f"TASK-{n}": EXECUTE_8 for n in range(1, 8)}

    rows = directly_follows(found, KEYS, tasks, ANALYTICS)

    edges = [
        (r["source"], r["target"], r["runs"], r["count"], r["share"], r["cut"]) for r in rows if r["skill"] == "work"
    ]
    assert edges == [
        ("[start]", "read", 6, 6, 1.0, False),
        ("edit", "lint", 3, 3, 0.5, True),
        ("edit", "test", 3, 3, 0.5, True),
        ("lint", "[end]", 3, 3, 1.0, False),
        ("read", "edit", 6, 6, 1.0, False),
        ("test", "[end]", 3, 3, 1.0, False),
    ]
    assert {(r["kind"], r["size"]) for r in rows} == {("execute", 8)}


def stretch(number: int, branch: str, *, skill: str | None = None, start: float = 0.0, reads: int = 10) -> list[Signal]:
    """A long run: `reads` reads, the activity `branch`, one of two, then nine fixes."""
    return run(
        number,
        *["read"] * reads,
        "edit" if branch == "edit" else "plan",
        "test" if number % 2 else "lint",
        *["fix"] * 9,
        skill=skill,
        start=start,
    )


def test_a_long_ungoverned_stretch_is_split_at_its_cuts_and_its_stages_report_their_weekly_stability() -> None:
    week = 100_000.0
    last = [s for n in range(1, 7) for s in stretch(n, "edit", start=week)]
    before = [s for n in range(11, 17) for s in stretch(n, "plan")]
    governed = [s for n in range(21, 27) for s in stretch(n, "edit", skill="work", start=week)]  # a machine models it
    short = [s for n in range(31, 37) for s in stretch(n, "edit", start=week, reads=2)]  # 14 activities: not long
    tasks = {f"TASK-{n}": EXECUTE_8 for n in (*range(1, 7), *range(11, 17))}
    tasks |= {f"TASK-{n}": {"labels": ["kind-execute", "size-3"]} for n in (*range(21, 27), *range(31, 37))}

    rows = sub_stages([*last, *before, *governed, *short], KEYS, tasks, ANALYTICS, since=50_000.0)

    assert [
        (r["kind"], r["size"], r["stage"], r["runs"], r["median_activities"], r["previous_runs"]) for r in rows
    ] == [
        ("execute", 8, "[start]", 6, 11, 6),
        ("execute", 8, "edit", 6, 10, 0),
        ("execute", 8, "plan", 0, None, 6),
    ]
    assert [r["stability"] for r in rows] == [pytest.approx(1 / 3)] * 3


TEST_FIRST = SkillMachine(
    "work",
    (MachineStage("RED", frozenset({"test"}), ok=False), MachineStage("GREEN", frozenset({"test"}), ok=True)),
)


def completed(number: int, *calls: str, steered: bool = False) -> list[Signal]:
    """`run`, then the request that loads the completion skill and delivers; a `steered` run gets a second human prompt."""
    s, branch = f"s{number}", f"claude/task-{number}-x"
    end = number * 1000 + len(calls) * 10 + 100
    found = [*run(number, *calls), sig("request", end, s, branch=branch, model="m")]
    found += [sig("skill", end + 0.1, s, branch=branch, name="completing-tasks")]
    found += [sig("deliver", end + 1, s, branch=branch)]
    if steered:
        found += [sig("prompt", number * 1000 - 5, s, branch=branch, turn="p1", detail="human")]
        found += [sig("prompt", end + 50, s, branch=branch, turn="p2", detail="human")]
    return found


def test_the_reference_is_the_fastest_conformant_clean_run_of_five_and_never_one_that_skipped_red() -> None:
    machine = Analytics(
        completion_skill="completing-tasks", stop_activities=frozenset({"Skill"}), skill_machines=(TEST_FIRST,)
    )
    group = [
        completed(1, "read", "edit", "test"),  # the fastest, and it never saw a test fail
        completed(2, "read", "edit", "test!", "edit", "test"),
        completed(3, "read", "edit", "test!", "edit", "test", "lint"),
        completed(4, "read", "read", "edit", "test!", "edit", "test", "lint"),
        completed(5, "read", "read", "read", "edit", "test!", "edit", "test", "lint"),
        completed(6, "read", "read", "read", "read", "edit", "test!", "edit", "test", "lint", "lint"),  # the slowest
        completed(7, "edit", steered=True),  # faster still, but an operator steered it
    ]
    four = [completed(n, "read", "edit", "test!", "test") for n in range(11, 15)]
    tasks = {f"TASK-{n}": EXECUTE_8 for n in range(1, 8)}
    tasks |= {f"TASK-{n}": {"labels": ["kind-execute", "size-3"]} for n in range(11, 15)}

    rows = fast_slow_diff([s for runs in (*group, *four) for s in runs], KEYS, tasks, machine)
    rows = [r for r in rows if r["skill"] == "work"]  # the completion skill's own transition is a group too

    assert rows == [
        {
            "kind": "execute",
            "size": 8,
            "skill": "work",
            "runs": 6,
            "conformant": 5,
            "reference": {"task": "TASK-2", "steps": 5},
            "slow": {"task": "TASK-6", "steps": 10},
            "slow_only": [{"activity": "read", "count": 3}, {"activity": "lint", "count": 2}],
            "reference_only": [],
        }
    ]


def test_a_group_of_five_with_no_conformant_run_is_listed_with_conformant_zero_and_no_reference() -> None:
    machine = Analytics(
        completion_skill="completing-tasks", stop_activities=frozenset({"Skill"}), skill_machines=(TEST_FIRST,)
    )
    group = [completed(n, *["read"] * (n - 1), "edit", "test") for n in range(1, 6)]  # every one skipped RED
    tasks = {f"TASK-{n}": EXECUTE_8 for n in range(1, 6)}

    rows = fast_slow_diff([s for runs in group for s in runs], KEYS, tasks, machine)
    rows = [r for r in rows if r["skill"] == "work"]

    assert rows == [
        {
            "kind": "execute",
            "size": 8,
            "skill": "work",
            "runs": 5,
            "conformant": 0,
            "reference": None,
            "slow": {"task": "TASK-5", "steps": 6},
            "slow_only": [
                {"activity": "read", "count": 4},
                {"activity": "edit", "count": 1},
                {"activity": "test", "count": 1},
            ],
            "reference_only": [],
        }
    ]


WORK_STEPS = SkillMachine(
    "work", (MachineStage("edit", frozenset({"edit"})), MachineStage("test", frozenset({"test"})))
)


def test_cost_to_go_is_the_closed_form_of_the_step_chain_over_the_machine_states() -> None:
    machine = Analytics(
        completion_skill="completing-tasks", stop_activities=frozenset({"Skill"}), skill_machines=(WORK_STEPS,)
    )
    # A step is in the stage its run had reached when it began: [start] until the first edit, then edit, then test.
    # [start] -> edit in all four runs, stays 2, 1, 1, 1 steps; edit -> test once in four, stays 1, 1, 2, 1; test stays 1
    runs = [("read", "edit", "test"), ("edit", "test"), ("edit", "edit", "test"), ("edit", "test", "read")]
    found = [s for n, calls in enumerate(runs, 1) for s in completed(n, *calls)]
    tasks = {f"TASK-{n}": EXECUTE_8 for n in range(1, 5)}

    rows = [r for r in cost_to_go(found, KEYS, tasks, machine) if r["skill"] == "work"]

    # Q = [[0, 1, 0], [0, 0, .25], [0, 0, 0]]: N = (I-Q)^-1 = [[1, 1, .25], [0, 1, .25], [0, 0, 1]]; h = (1.25, 1.25, 1)
    assert [(r["state"], r["n"], r["cost_to_go"]) for r in rows] == [
        ("[start]", 4, pytest.approx(1.25 + 1.25 + 0.25)),
        ("edit", 4, pytest.approx(1.25 + 0.25)),
        ("test", 1, pytest.approx(1.0)),
    ]
    assert {(r["kind"], r["size"]) for r in rows} == {("execute", 8)}
