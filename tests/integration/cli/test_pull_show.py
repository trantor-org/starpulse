"""`starpulse pull show`: one stored pull request as JSON, read from the server's PR store and never from GitHub."""

import json
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from starpulse.board.model.board_feed import BoardFeed
from starpulse.cli import agent_cli as cli
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.runtime.adapter_kit import serve, url

from tests.machines import MACHINES, ROLES

MERGE = "c0ffee" * 6 + "abcd"


def _pull(number: int, state: str, *, files: list[str] | None, merge: str | None = None) -> dict[str, Any]:
    return {
        "repo": "acme/app",
        "number": number,
        "state": state,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefOid": f"{number:040x}",
        "body": "render evidence",
        "checks": "pass",
        "requiredChecks": [],
        "threads": 0,
        "updatedAt": "2026-11-02T00:00:00Z",
        "mergedAt": "2026-11-02T01:00:00Z" if merge else None,
        "mergeSha": merge,
        "fetchedAt": 100.0,
        "detail": None if files is None else {"files": files, "mergeSha": merge},
    }


@pytest.fixture
def base(tmp_path: Path) -> Iterator[str]:
    store = PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))
    store.save(
        [
            _pull(5, "MERGED", files=["src/web/page.js", "README.md"], merge=MERGE),
            _pull(6, "OPEN", files=[]),
            _pull(7, "OPEN", files=None),
        ]
    )
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), pulls=store) as server:
        yield url(server, "")


def _run(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, Any]:
    code = cli.main(argv, {})
    out = capsys.readouterr()
    assert out.err == ""
    return code, json.loads(out.out)


@pytest.mark.parametrize("cited", ["acme/app#5", "https://github.com/acme/app/pull/5"])
def test_pull_show_prints_the_stored_state_merge_commit_and_changed_files(
    base: str, capsys: pytest.CaptureFixture[str], cited: str
) -> None:
    code, doc = _run(capsys, ["pull", "show", cited, "--server", base])

    assert code == 0
    assert (doc["repo"], doc["number"], doc["state"], doc["mergeSha"]) == ("acme/app", 5, "MERGED", MERGE)
    assert doc["files"] == ["src/web/page.js", "README.md"]


def test_pull_show_prints_no_files_as_an_empty_list_and_unknown_files_as_null(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _, none = _run(capsys, ["pull", "show", "acme/app#6", "--server", base])
    _, unknown = _run(capsys, ["pull", "show", "acme/app#7", "--server", base])

    assert (none["files"], unknown["files"]) == ([], None)


def test_pull_show_of_a_pull_request_the_store_does_not_hold_is_not_found(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["pull", "show", "acme/app#99", "--server", base])

    assert (code, doc["code"]) == (4, "not_found")


@pytest.mark.parametrize("cited", ["acme/app", "5", "acme/app#x", "https://example.test/acme/app/pull/5"])
def test_pull_show_refuses_a_citation_it_cannot_read(base: str, capsys: pytest.CaptureFixture[str], cited: str) -> None:
    code, doc = _run(capsys, ["pull", "show", cited, "--server", base])

    assert (code, doc["code"]) == (2, "usage")


def test_the_pulls_route_serves_files_for_one_pull_request_and_none_in_a_listing(base: str) -> None:
    with urllib.request.urlopen(f"{base}/api/pulls?repo=acme/app&number=5", timeout=5) as one:
        single = json.loads(one.read())["pulls"]
    with urllib.request.urlopen(f"{base}/api/pulls?repo=acme/app", timeout=5) as many:
        listed = json.loads(many.read())["pulls"]

    assert single[0]["files"] == ["src/web/page.js", "README.md"]
    assert all("files" not in pull for pull in listed)
