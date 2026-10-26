"""A task's recorded moves are judged against the machine they were made on: a move no transition declares is a violation."""

from starpulse.machine_engine.model.replay import check_events, check_lanes

#: new -> todo -> doing -> done, with `doing -> todo` as the only way back.
MACHINE = {
    "states": [
        {"id": "new", "initial": True, "final": False},
        {"id": "todo", "initial": False, "final": False},
        {"id": "doing", "initial": False, "final": False},
        {"id": "done", "initial": False, "final": True},
    ],
    "transitions": [
        {"source": "new", "target": "todo", "event": "CREATE"},
        {"source": "todo", "target": "doing", "event": "CLAIM"},
        {"source": "doing", "target": "todo", "event": "RETURN"},
        {"source": "doing", "target": "done", "event": "FINISH"},
    ],
}


def test_a_history_of_declared_moves_has_no_violation():
    rows = [("T-1", 1.0, None, "todo"), ("T-1", 2.0, "todo", "doing"), ("T-1", 3.0, "doing", "done")]

    report = check_lanes("board", MACHINE, rows)

    assert (report.replayed, report.violations) == (3, ())


def test_an_undeclared_move_is_grouped_by_its_lanes_with_a_count_and_example_tasks():
    rows = [
        ("T-1", 1.0, "todo", "done"),
        ("T-2", 2.0, "todo", "done"),
        ("T-1", 3.0, "done", "todo"),
        ("T-3", 4.0, "todo", "doing"),
    ]

    report = check_lanes("board", MACHINE, rows)

    assert report.replayed == 4
    assert [(v.source, v.move, v.count, v.tasks) for v in report.violations] == [
        ("todo", "done", 2, ("T-1", "T-2")),
        ("done", "todo", 1, ("T-1",)),
    ]


def test_a_task_first_seen_is_judged_from_the_initial_state():
    report = check_lanes("board", MACHINE, [("T-1", 1.0, None, "done")])

    assert [(v.source, v.move) for v in report.violations] == [("new", "done")]


def test_a_row_that_stays_in_its_lane_is_not_a_move():
    report = check_lanes("board", MACHINE, [("T-1", 1.0, "todo", "todo")])

    assert (report.replayed, report.violations) == (0, ())


def test_a_group_names_at_most_five_example_tasks():
    rows = [(f"T-{n}", float(n), "todo", "done") for n in range(8)]

    report = check_lanes("board", MACHINE, rows)

    assert report.violations[0].count == 8
    assert len(report.violations[0].tasks) == 5


def test_an_event_the_state_does_not_declare_is_a_violation_from_that_state():
    rows = [("T-1", 1.0, "CREATE"), ("T-1", 2.0, "FINISH"), ("T-1", 3.0, "CLAIM"), ("T-1", 4.0, "FINISH")]

    report = check_events("flow", MACHINE, rows)

    assert report.replayed == 4
    assert [(v.source, v.move, v.count, v.tasks) for v in report.violations] == [("todo", "FINISH", 1, ("T-1",))]


def test_an_event_that_leads_two_ways_leaves_the_task_in_either_state():
    machine = {
        **MACHINE,
        "transitions": [*MACHINE["transitions"], {"source": "doing", "target": "todo", "event": "FINISH"}],
    }

    report = check_events(
        "flow", machine, [("T-1", 1.0, "CREATE"), ("T-1", 2.0, "CLAIM"), ("T-1", 3.0, "FINISH"), ("T-1", 4.0, "CLAIM")]
    )

    assert report.violations == ()


def test_a_task_in_a_final_state_begins_again_from_the_initial_one():
    rows = [("T-1", 1.0, "CREATE"), ("T-1", 2.0, "CLAIM"), ("T-1", 3.0, "FINISH"), ("T-1", 4.0, "CREATE")]

    assert check_events("flow", MACHINE, rows).violations == ()


def test_each_task_is_replayed_on_its_own():
    rows = [("T-1", 1.0, "CREATE"), ("T-2", 2.0, "CLAIM")]

    report = check_events("flow", MACHINE, rows)

    assert [(v.source, v.move, v.tasks) for v in report.violations] == [("new", "CLAIM", ("T-2",))]
