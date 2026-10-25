"""The PR store holds the open pull requests and those updated within its window; older rows are read when asked for."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, event

from starpulse.pulls.pulls import PullStore

REPO = "acme/widgets"
NOW = datetime.now(UTC)


def _stamp(age: timedelta) -> str:
    return (NOW - age).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(number: int, state: str, age: timedelta, *, body: str = "", detail: dict | None = None) -> dict:
    return {
        "repo": REPO,
        "number": number,
        "state": state,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefOid": f"{number:040x}",
        "body": body,
        "checks": "none",
        "requiredChecks": [],
        "threads": 0,
        "updatedAt": _stamp(age),
        "mergedAt": None,
        "mergeSha": None,
        "fetchedAt": 900.0,
        "detail": detail,
    }


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """A database holding an open PR, a recently merged one and a merged one long past."""
    engine = create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}")
    PullStore(engine).save(
        [
            _record(1, "OPEN", timedelta(days=90), body="stale but open"),
            _record(2, "MERGED", timedelta(days=1), body="recent"),
            _record(3, "MERGED", timedelta(days=60), body="ancient needle", detail={"files": ["a.py"]}),
        ]
    )
    return engine


def _queries(engine: Engine) -> list[str]:
    """The statements `engine` runs from here on, appended as they run."""
    seen: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda _c, _cur, statement, *_: seen.append(statement))
    return seen


def test_a_merged_pull_request_outside_the_window_is_not_held_yet_resolves_by_number(engine: Engine) -> None:
    store = PullStore(engine, window=timedelta(days=7))
    seen = _queries(engine)

    assert [r["number"] for r in store.find(repo=REPO, number=2)] == [2]
    assert not seen

    (old,) = store.find(repo=REPO, number=3, detailed=True)
    assert (old["state"], old["detail"]) == ("MERGED", {"files": ["a.py"]})
    assert seen


def test_open_pull_requests_are_held_however_long_since_they_changed(engine: Engine) -> None:
    store = PullStore(engine, window=timedelta(days=7))
    seen = _queries(engine)

    assert [r["number"] for r in store.find(state="OPEN")] == [1]
    assert not seen


def test_an_unfiltered_find_still_lists_every_row_in_order(engine: Engine) -> None:
    store = PullStore(engine, window=timedelta(days=7))

    assert [r["number"] for r in store.find()] == [1, 2, 3]
    assert [r["number"] for r in store.find(repo=REPO, state="MERGED")] == [2, 3]
    assert [r["number"] for r in store.find(body_contains="NEEDLE")] == [3]


def test_a_saved_record_is_held_and_replaces_the_stored_row(engine: Engine) -> None:
    store = PullStore(engine, window=timedelta(days=7))
    store.save([_record(3, "MERGED", timedelta(days=60), body="rewritten")])
    seen = _queries(engine)

    (record,) = store.find(repo=REPO, number=3)
    assert record["body"] == "rewritten"
    assert not seen
    assert [r["number"] for r in store.find()] == [1, 2, 3]


def test_a_number_the_store_lacks_finds_nothing(engine: Engine) -> None:
    assert PullStore(engine, window=timedelta(days=7)).find(repo=REPO, number=99) == []


def test_held_only_leaves_out_what_a_read_of_the_database_would_add(engine: Engine) -> None:
    store = PullStore(engine, window=timedelta(days=7))
    seen = _queries(engine)

    assert [r["number"] for r in store.find(repo=REPO, held_only=True)] == [1, 2]
    assert not seen
