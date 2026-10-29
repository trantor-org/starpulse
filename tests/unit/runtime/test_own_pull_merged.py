"""The scheduler asks `own_pull_merged` about every Ready task on every tick; it must not rescan the pull request table
each time (TASK-9620: the rescans held the scheduler-loop thread at 19% of a core)."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine, create_engine, event
from starpulse.pulls.pulls import PullStore
from starpulse.runtime.assembly import own_pull_merged

REPO = "acme/widgets"
URL = f"https://github.com/{REPO}/pull/7"
STAMP = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(number: int, state: str, merged_at: str | None = None) -> dict:
    return {
        "repo": REPO,
        "number": number,
        "state": state,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefOid": f"{number:040x}",
        "body": "",
        "checks": "none",
        "requiredChecks": [],
        "threads": 0,
        "updatedAt": STAMP,
        "mergedAt": merged_at,
        "mergeSha": None,
        "fetchedAt": 900.0,
        "detail": None,
    }


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}")
    PullStore(engine).save([_record(7, "OPEN")])
    return engine


def _agent(*prs: str) -> dict:
    return {"id": "TASK-1", "prs": list(prs)}


def test_a_task_citing_no_pull_request_is_not_delivered(engine: Engine) -> None:
    assert own_pull_merged(SimpleNamespace(engine=engine), _agent()) is False


def test_an_open_pull_request_is_not_delivered_until_it_merges(engine: Engine) -> None:
    log = SimpleNamespace(engine=engine)
    assert own_pull_merged(log, _agent(URL)) is False

    PullStore(engine).save([_record(7, "MERGED", STAMP)])

    assert own_pull_merged(log, _agent(URL)) is True


def test_repeated_asks_read_only_the_cited_rows(engine: Engine) -> None:
    log = SimpleNamespace(engine=engine)
    own_pull_merged(log, _agent(URL))
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda _c, _cur, statement, *_: statements.append(statement))

    for _ in range(20):
        own_pull_merged(log, _agent())
        own_pull_merged(log, _agent(URL))

    assert [statement for statement in statements if "number) IN" not in statement] == []
