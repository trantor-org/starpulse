"""A read of one pull request answers within the page's budget however many the store holds and whatever else is
being computed."""

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.views.adapters.inbound.api import pulls as pulls_route
from starpulse.views.adapters.inbound.api.pulls import PullReads

REPO = "acme/widgets"
BUDGET_S = 0.05
HOLDINGS = 6000
LOOKUPS = 20


def _record(number: int) -> dict:
    stamp = (datetime.now(UTC) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "repo": REPO,
        "number": number,
        "state": "MERGED",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefOid": f"{number:040x}",
        "body": "x" * 2000,
        "checks": "none",
        "requiredChecks": [],
        "threads": 0,
        "updatedAt": stamp,
        "mergedAt": stamp,
        "mergeSha": None,
        "fetchedAt": 900.0,
        "detail": None,
    }


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    """A store holding `HOLDINGS` merged pull requests long past the window, which only the database holds."""
    engine = create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}")
    PullStore(engine).save([_record(number) for number in range(1, HOLDINGS + 1)])
    return PullStore(engine)


def _lookup(reads: PullReads, number: int) -> float:
    started = time.perf_counter()
    encoded, status = reads(f"repo={REPO}&number={number}")
    assert status == 200
    assert f'"number":{number}' in encoded.body.decode().replace(" ", "")
    return time.perf_counter() - started


def test_a_single_pull_request_read_computes_under_the_budget_in_a_store_of_thousands(store: PullStore) -> None:
    reads = PullReads(store)
    _lookup(reads, 1)

    took = sorted(_lookup(reads, number) for number in range(2, LOOKUPS + 2))

    assert took[-1] < BUDGET_S


def test_a_single_pull_request_read_does_not_wait_for_the_list_being_rebuilt(
    store: PullStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    rebuilding, release = threading.Event(), threading.Event()
    real: Callable[..., Any] = pulls_route.pulls_response

    def slow_list(pulls: PullStore | None, query: dict[str, list[str]]) -> Any:
        if "number" not in query:
            rebuilding.set()
            release.wait(10)
        return real(pulls, query)

    monkeypatch.setattr(pulls_route, "pulls_response", slow_list)
    reads = PullReads(store)
    rebuild = threading.Thread(target=reads, args=("",))
    rebuild.start()
    assert rebuilding.wait(5)
    answered: list[float] = []
    lookups = threading.Thread(target=lambda: answered.extend(_lookup(reads, n) for n in range(1, LOOKUPS + 1)))

    lookups.start()
    lookups.join(5)
    release.set()
    rebuild.join(10)

    assert not lookups.is_alive()
    assert max(answered) < BUDGET_S
