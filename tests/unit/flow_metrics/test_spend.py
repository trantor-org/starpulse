"""The spend report: per task and phase, the tokens a task burned, with its weighted total against its cell's norm."""

import re
from itertools import count

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.flow_metrics.model.spend import spend_report
from starpulse.harness_telemetry.adapters.inbound.telemetry import CLAUDE_CODE, Signal

KEYS = TaskKeys(
    key=re.compile(r"TASK-\d+"),
    branch=re.compile(r"(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", re.IGNORECASE),
    key_format="TASK-{}",
)
ANALYTICS = Analytics(completion_skill="completing-tasks")
_N = count()
EXECUTE_3 = ["kind-execute", "size-3"]


def sig(kind: str, at: float, session: str, **fields: object) -> Signal:
    return Signal(CLAUDE_CODE, session, kind, at, f"{session}:{next(_N)}", **fields)  # type: ignore[arg-type]


def request(at: float, number: int, **tokens: int) -> Signal:
    return sig("request", at, f"s{number}", branch=f"claude/task-{number}-x", model="m", turn="p1", **tokens)


def lifecycle(number: int, *, extra: int = 0) -> list[Signal]:
    """TASK-`number`: a request, then three that edit and implement, one under qa (a subagent's) and one under
    deliver; `extra` more output tokens on the last."""
    s, branch = f"s{number}", f"claude/task-{number}-x"
    return [
        sig("prompt", 0, s, branch=branch, turn="p1", detail="human"),
        request(1, number, input=100, output=10),
        request(2, number, cache_read=1000, output=10),
        sig("tool", 2, s, branch=branch, name="Edit", turn="p1"),
        request(3, number, cache_read=2000, cache_write=400, output=20),
        request(4, number, cache_read=3000, output=20),
        sig("compaction", 4.5, s, branch=branch, name="auto", turn="p1"),
        sig("skill", 6, s, branch=branch, name="qa", turn="p1"),
        sig("request", 6, s, branch=branch, model="side-m", origin="side", turn="p1", input=50, output=5),
        sig("skill", 8, s, branch=branch, name="deliver", turn="p1"),
        request(8, number, cache_read=4000, output=10 + extra),
    ]


def test_a_task_reports_one_row_per_phase_in_order_with_weighted_tokens_models_and_compactions() -> None:
    rows = spend_report(lifecycle(1), KEYS, {"TASK-1": {"labels": EXECUTE_3}}, ANALYTICS)

    assert [r["phase"] for r in rows] == ["claim", "implement", "qa", "deliver"]
    claim, implement, qa, deliver = rows
    assert (claim["task"], claim["kind"], claim["size"]) == ("TASK-1", "execute", 3)
    assert (claim["steps"], claim["input"], claim["output"], claim["cache_read"]) == (1, 100, 10, 0)
    assert claim["wte"] == 100 + 5 * 10
    assert (implement["steps"], implement["cache_write"], implement["compactions"]) == (3, 400, 1)
    assert implement["wte"] == 0.1 * 6000 + 1.25 * 400 + 5 * 50
    assert implement["peak_context"] == 3000
    assert (qa["steps"], qa["side_steps"], qa["models"]) == (1, 1, ["side-m"])
    assert deliver["models"] == ["m"]
    assert all(r["task_wte"] == sum(p["wte"] for p in rows) for r in rows)


def test_an_edit_under_deliver_bills_implement_and_the_steps_around_it_stay_deliver() -> None:
    s, branch = "s7", "claude/task-7-x"
    signals = [
        sig("prompt", 0, s, branch=branch, turn="p1", detail="human"),
        sig("skill", 1, s, branch=branch, name="deliver", turn="p1"),
        request(2, 7, output=10),
        request(3, 7, output=10),
        sig("tool", 3, s, branch=branch, name="Edit", turn="p1"),
        request(4, 7, output=10),
    ]

    rows = spend_report(signals, KEYS, {"TASK-7": {"labels": EXECUTE_3}}, ANALYTICS)

    assert {r["phase"]: r["steps"] for r in rows} == {"deliver": 2, "implement": 1}


def test_a_task_far_above_its_cells_median_is_flagged_and_a_cell_under_five_tasks_has_no_norm() -> None:
    tasks = {f"TASK-{n}": {"labels": EXECUTE_3} for n in range(1, 8)}
    found = [s for n in range(1, 7) for s in lifecycle(n)] + lifecycle(7, extra=100_000)

    rows = spend_report(found, KEYS, tasks, ANALYTICS)

    normal = next(r for r in rows if r["task"] == "TASK-1")
    heavy = next(r for r in rows if r["task"] == "TASK-7")
    assert normal["above_norm"] is False
    assert heavy["above_norm"] is True
    assert heavy["norm_wte"] == normal["task_wte"]
    assert heavy["task_wte"] > 10 * heavy["norm_wte"]

    few = spend_report([s for n in (1, 2) for s in lifecycle(n)], KEYS, tasks, ANALYTICS)
    assert {(r["norm_wte"], r["above_norm"]) for r in few} == {(None, False)}


def test_two_phases_of_a_task_starting_at_the_same_instant_still_take_its_compactions() -> None:
    branch = "claude/task-1-x"
    found = [
        *[sig("skill", 5, s, branch=branch, name=skill, turn="p1") for s, skill in (("sa", "qa"), ("sb", "deliver"))],
        *[sig("request", 5, s, branch=branch, model="m", turn="p1", input=10) for s in ("sa", "sb")],
        sig("compaction", 6, "sa", branch=branch, name="auto", turn="p1"),
    ]

    rows = spend_report(found, KEYS, {"TASK-1": {"labels": EXECUTE_3}}, ANALYTICS)

    assert sorted(r["phase"] for r in rows) == ["deliver", "qa"]
    assert sum(r["compactions"] for r in rows) == 1


def test_each_row_carries_the_row_profile_of_its_first_main_thread_step() -> None:
    branch = "claude/task-1-x"
    found = [
        sig("request", 1, "s1", branch=branch, model="opus", effort="high", turn="p1", input=10),
        sig("request", 2, "s1", branch=branch, model="opus", effort="low", turn="p1", input=10),
        sig("skill", 3, "s1", branch=branch, name="qa", turn="p1"),
        sig("request", 3, "s1", branch=branch, model="haiku", effort="", origin="side", turn="p1", input=10),
        sig("request", 4, "s1", branch=branch, model="sonnet", effort="medium", turn="p1", input=10),
    ]

    rows = spend_report(found, KEYS, {"TASK-1": {"labels": EXECUTE_3}}, ANALYTICS)

    assert [(r["phase"], r["profile"]) for r in rows] == [("implement", "opus-high"), ("qa", "sonnet-medium")]

    side_only = spend_report(found[2:4], KEYS, {}, ANALYTICS)
    assert [r["profile"] for r in side_only] == ["haiku-unknown"]
