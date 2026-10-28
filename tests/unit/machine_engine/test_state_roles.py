"""`StateRoles` answers where a lifecycle's points are from the roles a machine declares, never from a State's name."""

from pathlib import Path

import pytest
from starpulse.machine_engine.adapters.machine_loader import load_machine
from starpulse.machine_engine.model.state_roles import StateRoles

FIXTURES = Path(__file__).parents[2] / "fixtures" / "machines"


def renamed() -> StateRoles:
    return StateRoles.of_machine(load_machine(FIXTURES / "renamed-board.yaml"))


@pytest.mark.parametrize(
    ("point", "state"),
    [
        ("initial", "inbox"),
        ("final", "gone"),
        ("done", "shipped"),
        ("working", "doing"),
        ("ready", "todo"),
        ("waiting", "parked"),
        ("review", "checking"),
        ("attention", "on_me"),
    ],
)
def test_a_machine_with_renamed_states_answers_each_lifecycle_point_by_its_role(point: str, state: str) -> None:
    assert getattr(renamed(), point) == state


def test_the_startable_states_are_the_ones_waiting_on_a_start_fact_or_a_person_and_never_the_review_wait() -> None:
    assert renamed().startable == frozenset({"todo", "parked", "on_me"})


def test_a_board_of_statuses_alone_starts_at_the_first_works_in_the_second_and_ends_at_the_last() -> None:
    roles = StateRoles.of_statuses(("To Do", "In Progress", "Done"))

    assert (roles.initial, roles.working, roles.done, roles.final) == ("to_do", "in_progress", "done", "done")
    assert (roles.ready, roles.waiting, roles.review, roles.attention) == (None, None, None, None)
    assert roles.startable == frozenset()


def test_a_review_that_waits_on_a_merge_is_still_the_review_wait_and_a_person_waiting_on_a_merge_is_startable() -> None:
    roles = StateRoles(
        {"todo": "waiting_on_fact", "checking": "waiting_on_fact", "on_me": "waiting_on_person", "shipped": "resting"},
        {
            "todo": {"criteria_unmet": "CRITERIA_UNMET"},
            "checking": {"pr_merged": "MERGED"},
            "on_me": {"pr_merged": "MERGED"},
        },
        ("shipped",),
    )

    assert roles.review == "checking"
    assert roles.startable == frozenset({"todo", "on_me"})
