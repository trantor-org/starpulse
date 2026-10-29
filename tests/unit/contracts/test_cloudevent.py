"""The CloudEvent every producer builds and the ingest reads: one model for both ends of the wire."""

import pytest
from pydantic import ValidationError

from starpulse import contracts


def test_a_producer_builds_an_event_with_the_spec_version_and_a_fresh_id() -> None:
    first = contracts.CloudEvent(
        source="dagu", type="StepStarted", subject="r1", data={"workflow": "w", "status": "running"}
    )
    second = contracts.CloudEvent(source="dagu", type="StepStarted", subject="r1")

    assert first.specversion == "1.0"
    assert first.id and first.id != second.id


def test_the_wire_form_omits_what_the_event_does_not_set_and_stamps_the_time_with_its_offset() -> None:
    event = contracts.CloudEvent(id="e1", source="ci", type="BUILT", subject="PROJ-1", time="2026-10-18T22:00:00Z")

    assert event.wire() == {
        "specversion": "1.0",
        "id": "e1",
        "source": "ci",
        "type": "BUILT",
        "subject": "PROJ-1",
        "time": "2026-10-18T22:00:00Z",
    }


@pytest.mark.parametrize(
    "attributes",
    [
        {"specversion": "0.3"},
        {"id": ""},
        {"source": ""},
        {"time": "yesterday"},
        {"time": "2026-10-18T22:00:00"},  # no offset
        {"data": [1]},
    ],
)
def test_an_event_the_spec_refuses_is_refused_at_construction(attributes: dict) -> None:
    with pytest.raises(ValidationError):
        contracts.CloudEvent(**{"id": "e1", "source": "ci", "type": "BUILT", **attributes})
