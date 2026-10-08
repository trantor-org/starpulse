"""GET /api/doctor: the contract checks `starpulse doctor` runs, served to the page that draws the Ledger's banner."""

import json
import urllib.request
from pathlib import Path

from starpulse.api.adapter_kit import serve, url
from starpulse.api.server import _cached
from starpulse.projections.board_feed import BoardFeed
from starpulse.projections.doctor import contract
from starpulse.settings.config import Config, Repo, RunsInstance
from starpulse.tests.hosts import FakeHost

CONFIG = Config(
    None, "ic", (RunsInstance("ci", "dagu", "http://dagu:8080"),), repos=(Repo("child", "child", "pin-bump"),)
)
SNAPSHOT = {"dags": [{"name": "ci/apply"}], "cues": [{"event": "MERGED", "dag": "ci/apply", "on": "merge"}]}


def test_the_contract_checks_are_the_cue_and_repository_checks_of_the_install() -> None:
    report = contract(SNAPSHOT, CONFIG, FakeHost().probes())

    assert [c["check"] for c in report["checks"]] == ["cue:ci/apply", "repo:child"]
    assert (
        report["ok"] is False
    )  # the cue declares no `[runs.commit]` after key: a warning; the repo is no submodule: a failure


def test_the_page_reads_the_contract_report_from_the_server(tmp_path: Path) -> None:
    served = {"ok": True, "checks": [{"check": "cue:ci/apply", "status": "pass", "reason": "ci/apply declares AFTER"}]}
    with (
        serve(tmp_path, BoardFeed(), contract=lambda: served) as server,
        urllib.request.urlopen(url(server, "/api/doctor"), timeout=5) as resp,
    ):
        body = json.loads(resp.read())

    assert body == served


def test_a_server_with_no_contract_to_check_serves_an_empty_passing_report(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed()) as server, urllib.request.urlopen(url(server, "/api/doctor"), timeout=5) as resp:
        body = json.loads(resp.read())

    assert body == {"ok": True, "checks": []}


def test_the_report_is_read_once_a_minute_however_often_the_page_asks() -> None:
    reads: list[int] = []
    now = [0.0]

    def read() -> dict:
        reads.append(1)
        return {"ok": True, "checks": []}

    get = _cached(read, 60, lambda: now[0])

    get(), get()
    now[0] = 59.9
    get()
    assert len(reads) == 1

    now[0] = 60.0
    get()
    assert len(reads) == 2
