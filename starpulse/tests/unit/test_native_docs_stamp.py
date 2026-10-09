"""A doc's `created_date` and `updated_date` are UTC, whatever zone the host runs in."""

import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from starpulse._internal.adapters.boards import native


@pytest.fixture
def phoenix(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The host clock in MST (UTC-7), the zone the stamp once leaked."""
    monkeypatch.setenv("TZ", "America/Phoenix")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _utc_minutes(call: object) -> tuple[set[str], list[str]]:
    """The UTC minutes either side of `call` (the allowed stamps) and the stamps `call` returned."""
    start = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    stamps = call()  # type: ignore[operator]
    end = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    return {start, end}, stamps


def test_native_doc_create_and_edit_stamp_the_current_utc_minute_on_a_host_in_another_zone(
    tmp_path: Path, phoenix: None
) -> None:
    built = native.board({}, tmp_path)
    assert built.create_doc is not None
    assert built.edit_doc is not None
    assert built.read_doc is not None

    def created() -> list[str]:
        assert built.create_doc("Plan", {"body": "x\n"}).ok
        record = built.read_doc("doc-1")
        return [record["created_date"], record["updated_date"]]

    allowed, stamps = _utc_minutes(created)
    assert set(stamps) <= allowed

    def edited() -> list[str]:
        assert built.edit_doc("doc-1", {"body": "y\n"}).ok
        return [built.read_doc("doc-1")["updated_date"]]

    allowed, stamps = _utc_minutes(edited)
    assert set(stamps) <= allowed
