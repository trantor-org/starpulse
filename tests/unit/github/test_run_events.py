import json

import pytest

from starpulse.github.model.events import run_event_of

REPO = "acme/widgets"


def delivery(status: str, conclusion: str | None = None, *, attempt: int = 1) -> bytes:
    run = {"id": 77, "run_attempt": attempt, "path": ".github/workflows/ci.yml", "status": status, "conclusion": conclusion}
    return json.dumps({"action": status, "repository": {"full_name": REPO}, "workflow_run": run}).encode()


@pytest.mark.parametrize(
    ("status", "conclusion", "event", "mapped"),
    [
        ("requested", None, "StepStarted", "queued"),
        ("in_progress", None, "StepStarted", "running"),
        ("completed", "success", "StepFinished", "succeeded"),
        ("completed", "cancelled", "StepFinished", "aborted"),
        ("completed", "timed_out", "StepFinished", "failed"),
    ],
)
def test_workflow_run_delivery_becomes_a_run_event(status, conclusion, event, mapped):
    posted = run_event_of("workflow_run", delivery(status, conclusion))

    assert posted == {
        "specversion": "1.0",
        "id": posted["id"],
        "source": "github",
        "type": event,
        "subject": "77",
        "data": {"workflow": "ci.yml", "status": mapped},
    }


def test_a_redelivery_keeps_its_id_and_a_rerun_gets_another():
    first = run_event_of("workflow_run", delivery("in_progress"))
    again = run_event_of("workflow_run", delivery("in_progress"))
    rerun = run_event_of("workflow_run", delivery("in_progress", attempt=2))

    assert first["id"] == again["id"] != rerun["id"]


@pytest.mark.parametrize(
    ("event", "body"),
    [
        ("pull_request", delivery("in_progress")),
        ("workflow_run", b"not json"),
        ("workflow_run", delivery("surprise")),
        ("workflow_run", json.dumps({"repository": {"full_name": REPO}, "workflow_run": {"id": 1}}).encode()),
    ],
)
def test_other_deliveries_are_no_run_event(event, body):
    assert run_event_of(event, body) is None
