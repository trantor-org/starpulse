"""The estimate report: each completed task's size label, kind and profile beside its measured steps, active minutes and
the size step its effort landed at."""

from starpulse.flow_metrics.model.estimates import estimate_report

#: Size -> (steps p90, active minutes p90), as the sizing ADR's table gives them.
BANDS = ((1, 50, 14.0), (2, 62, 19.0), (3, 144, 44.0), (5, 170, 47.0), (8, 175, 61.0))


def slice_(task: str, *, steps: int, side: int = 0, active: float = 0.0, wait: float = 0.0, complete: bool = True):
    return {
        "task": task,
        "steps": steps,
        "side_steps": side,
        "active_s": active,
        "operator_wait_s": wait,
        "complete": complete,
    }


def task(*labels: str, milestone: str | None = "m-305", profile: str | None = "@agent-standard-high") -> dict:
    return {"labels": list(labels), "milestone": milestone, "profile": profile}


def test_a_completed_task_carries_its_estimate_beside_its_measured_actuals() -> None:
    rows = estimate_report(
        [slice_("TASK-1", steps=60, side=10, active=1200.0, wait=300.0)],
        {"TASK-1": task("kind-execute", "size-2")},
        BANDS,
    )

    assert rows == [
        {
            "task": "TASK-1",
            "milestone": "m-305",
            "kind": "execute",
            "size": 2,
            "profile": "@agent-standard-high",
            "steps": 70,
            "active_minutes": 25.0,
            "effort_size": 3,
            "effort_size_step": 1,
        }
    ]


def test_effort_past_the_largest_band_has_no_size_and_steps_one_past_the_top() -> None:
    [row] = estimate_report([slice_("TASK-1", steps=400)], {"TASK-1": task("kind-execute", "size-5")}, BANDS)

    assert (row["effort_size"], row["effort_size_step"]) == (None, 2)


def test_effort_under_the_label_is_a_negative_step() -> None:
    [row] = estimate_report([slice_("TASK-1", steps=10)], {"TASK-1": task("kind-execute", "size-5")}, BANDS)

    assert (row["effort_size"], row["effort_size_step"]) == (1, -3)


def test_no_bands_leave_the_effort_unmeasured_but_keep_the_rest() -> None:
    [row] = estimate_report([slice_("TASK-1", steps=10)], {"TASK-1": task("kind-execute", "size-5")}, ())

    assert (row["steps"], row["effort_size"], row["effort_size_step"]) == (10, None, None)


def test_only_completed_labelled_tasks_of_the_milestone_are_listed() -> None:
    tasks = {
        "TASK-1": task("kind-execute", "size-2"),
        "TASK-2": task("kind-execute", "size-2"),
        "TASK-3": task("kind-execute"),
        "TASK-4": task("kind-execute", "size-2", milestone="m-9"),
    }
    slices = [
        slice_("TASK-1", steps=5),
        slice_("TASK-2", steps=5, complete=False),
        slice_("TASK-3", steps=5),
        slice_("TASK-4", steps=5),
        slice_("TASK-5", steps=5),
    ]

    assert [r["task"] for r in estimate_report(slices, tasks, BANDS, milestone="m-305")] == ["TASK-1"]
    assert [r["task"] for r in estimate_report(slices, tasks, BANDS)] == ["TASK-1", "TASK-4"]
