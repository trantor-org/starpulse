"""The checked-in `github-pull-request` machine: the conflict events record a fact without moving the pull request."""

import pytest
from starpulse.machine_engine.model.machine_definition import writers_of
from starpulse.pulls.adapters.outbound.github import PULL_REQUEST

OPEN_STATES = ["open", "checks_failed", "checks_passed"]


def _in(state: str):
    machine = PULL_REQUEST.machine()
    machine.send("PR_OPENED")
    if state != "open":
        machine.send({"checks_failed": "CHECKS_FAILED", "checks_passed": "CHECKS_PASSED"}[state])
    return machine


@pytest.mark.parametrize("event", ["CONFLICTED", "MERGEABLE"])
@pytest.mark.parametrize("state", OPEN_STATES)
def test_a_conflict_event_leaves_an_open_pull_request_in_its_state(state: str, event: str) -> None:
    machine = _in(state)
    machine.send(event)
    assert [s.id for s in machine.configuration] == [state]


@pytest.mark.parametrize("event", ["CONFLICTED", "MERGEABLE"])
def test_ci_writes_a_conflict_event(event: str) -> None:
    assert [w.actor for w in writers_of(PULL_REQUEST.machine)[event]] == ["ci"]
