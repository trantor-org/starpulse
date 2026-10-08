"""The GitHub adapter: recorded pull requests, check runs and Copilot activity become keyed events on two machines.

The fixtures are responses recorded off public Copilot pull requests (`jeremytrimble/specview` #46 and #38), cut to the
fields the adapter reads and with every person but the Copilot bots replaced by `operator`. The names they pin
(`copilot_work_started`, `copilot_work_finished`, `dynamic` runs named for the Copilot cloud agent, reviews by
`copilot-pull-request-reviewer[bot]`) are undocumented by GitHub, so a rename fails here and not on a page.
"""

import json
import re
import threading
from copy import deepcopy
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest

from starpulse.adapters.runs.github import GITHUB_MACHINES, GitHubAdapter, poll, read
from starpulse.adapters.runs.github_actions import connect
from starpulse.api.adapter_kit import MachineEventsAdapterKit
from starpulse.contracts.adapters import TaskKeys
from starpulse.store.event_log import EventLog, Tail
from starpulse.tests.machines import MACHINES

FIXTURES = Path(__file__).parents[1] / "fixtures" / "github"
REPO = "jeremytrimble/specview"
PROJ = TaskKeys(key=re.compile(r"PROJ-\d+"), branch=re.compile(r"(?:refs/heads/)?(?:[\w-]+/)?(PROJ-\d+)"))


def fixture(name: str, branch: str | None = None) -> dict:
    bundle = json.loads((FIXTURES / f"{name}.json").read_text())
    if branch:
        bundle["pull"]["head"]["ref"] = branch
    return bundle


def at(stamp: str) -> float:
    return datetime.fromisoformat(stamp).timestamp()


def adapter() -> GitHubAdapter:
    return GitHubAdapter(keys=PROJ)


def summary(events: list[dict]) -> list[tuple[str, str, str, float]]:
    return [(e["machine"], e["event"], e["actor"], e["time"]) for e in events]


def test_a_copilot_pull_request_maps_its_work_timeline_and_dynamic_runs_in_time_order() -> None:
    events = adapter().events(REPO, fixture("copilot-pull"))

    assert summary(events) == [
        ("copilot", "RUN_STARTED", "copilot", at("2026-10-06T22:53:35Z")),
        ("github-pull-request", "PR_OPENED", "Copilot", at("2026-10-06T22:54:55Z")),
        ("copilot", "RUN_FINISHED", "copilot", at("2026-10-06T22:55:38Z")),
        ("copilot", "WORK_FINISHED", "operator", at("2026-10-06T22:55:40Z")),
        ("copilot", "WORK_STARTED", "operator", at("2026-10-06T22:55:40Z")),
        ("copilot", "RUN_STARTED", "copilot", at("2026-10-06T22:56:35Z")),
        ("copilot", "WORK_STARTED", "operator", at("2026-10-06T22:56:44Z")),
    ]


def test_a_merged_pull_request_maps_its_reviewer_bot_review_check_rollup_and_merge() -> None:
    events = adapter().events(REPO, fixture("reviewed-pull"))

    assert summary(events) == [
        ("github-pull-request", "PR_OPENED", "operator", at("2026-05-16T16:04:48Z")),
        ("copilot", "WORK_STARTED", "operator", at("2026-05-16T16:17:37Z")),
        ("copilot", "REVIEW_SUBMITTED", "copilot-pull-request-reviewer[bot]", at("2026-05-16T16:20:23Z")),
        ("github-pull-request", "PR_MERGED", "github", at("2026-05-17T13:02:44Z")),
        ("github-pull-request", "CHECKS_PASSED", "github", at("2026-05-17T13:04:16Z")),
    ]


def test_a_review_by_anyone_but_the_copilot_reviewer_is_no_copilot_event() -> None:
    bundle = fixture("reviewed-pull")
    bundle["reviews"][0]["user"] = {"login": "operator", "type": "User"}

    assert "REVIEW_SUBMITTED" not in [e["event"] for e in adapter().events(REPO, bundle)]


def test_a_failed_check_run_fails_the_rollup_and_a_running_one_leaves_it_undecided() -> None:
    failed, running = fixture("reviewed-pull"), fixture("reviewed-pull")
    failed["check_runs"]["check_runs"][0]["conclusion"] = "failure"
    running["check_runs"]["check_runs"][0].update(status="in_progress", conclusion=None, completed_at=None)

    checks = lambda bundle: [e["event"] for e in adapter().events(REPO, bundle) if e["event"].startswith("CHECKS")]  # noqa: E731

    assert (checks(failed), checks(running)) == (["CHECKS_FAILED"], [])


def test_a_pull_request_closed_unmerged_is_closed_not_merged() -> None:
    bundle = fixture("reviewed-pull")
    bundle["pull"]["merged_at"] = None

    events = adapter().events(REPO, bundle)

    assert [e["event"] for e in events if e["event"] in ("PR_MERGED", "PR_CLOSED")] == ["PR_CLOSED"]


def test_an_open_pull_request_has_neither_merged_nor_closed() -> None:
    assert {e["event"] for e in adapter().events(REPO, fixture("copilot-pull"))} == {
        "PR_OPENED",
        "RUN_STARTED",
        "RUN_FINISHED",
        "WORK_STARTED",
        "WORK_FINISHED",
    }


def test_the_copilot_code_review_run_maps_to_review_run_events() -> None:
    bundle = fixture("copilot-pull")
    for run in bundle["runs"]["workflow_runs"]:
        run["name"] = run["name"].replace("cloud agent", "Code Review")  # the ADR's second documented run name

    events = [e["event"] for e in adapter().events(REPO, bundle) if e["event"].startswith("REVIEW_RUN")]

    assert events == ["REVIEW_RUN_STARTED", "REVIEW_RUN_FINISHED", "REVIEW_RUN_STARTED"]


def test_an_event_is_keyed_by_the_task_its_branch_names_else_by_the_pull_request() -> None:
    keyed = adapter().events(REPO, fixture("copilot-pull", "copilot/PROJ-7-x"))
    unkeyed = adapter().events(REPO, fixture("copilot-pull"))

    assert {(e["task"], e["run"]) for e in keyed} == {("PROJ-7", None)}
    assert {(e["task"], e["run"]) for e in unkeyed} == {(None, f"{REPO}#46")}


def test_every_event_id_is_unique_and_stable_across_reads() -> None:
    first = adapter().events(REPO, fixture("copilot-pull"))
    again = adapter().events(REPO, deepcopy(fixture("copilot-pull")))

    assert [e["event_id"] for e in first] == [e["event_id"] for e in again]
    assert len({e["event_id"] for e in first}) == len(first)


class TestGitHubAdapter(MachineEventsAdapterKit):
    keys = PROJ
    branches = {"copilot/PROJ-1-add-x": "PROJ-1", "refs/heads/PROJ-2": "PROJ-2", "main": None}
    machines = MACHINES | GITHUB_MACHINES

    def produce(self) -> list[dict]:
        return [
            *adapter().events(REPO, fixture("copilot-pull", "copilot/PROJ-1-add-x")),
            *adapter().events(REPO, fixture("reviewed-pull", "refs/heads/PROJ-2")),
            *adapter().events(REPO, fixture("copilot-pull")),
        ]


class Recorded:
    """A GitHub REST API answering from a recorded bundle, the way the transport hands it back: an array body is `{"items": [...]}`."""

    def __init__(self, *bundles: dict) -> None:
        self.calls: list[str] = []
        self.served: dict[str, tuple[int, dict]] = {}
        pulls = [b["pull"] for b in bundles]
        self.served[f"/repos/{REPO}/pulls?state=all&sort=updated&direction=desc&per_page=30"] = (200, {"items": pulls})
        for bundle in bundles:
            pull = bundle["pull"]
            base = f"/repos/{REPO}"
            ref = quote(pull["head"]["ref"], safe="")
            self.served |= {
                f"{base}/pulls/{pull['number']}": (200, pull),
                f"{base}/issues/{pull['number']}/timeline?per_page=100&page=1": (200, {"items": bundle["timeline"]}),
                f"{base}/pulls/{pull['number']}/reviews?per_page=100&page=1": (200, {"items": bundle["reviews"]}),
                f"{base}/commits/{pull['head']['sha']}/check-runs?per_page=100": (200, bundle["check_runs"]),
                f"{base}/actions/runs?branch={ref}&per_page=100": (200, bundle["runs"]),
            }

    def __call__(self, method: str, path: str, body: dict | None) -> tuple[int, dict]:
        self.calls.append(path)
        return self.served.get(path, (404, {}))


def test_read_assembles_a_pull_requests_bundle_from_its_five_endpoints() -> None:
    bundle = fixture("copilot-pull")

    assert read(Recorded(bundle), REPO, 46) == bundle


def test_read_pages_the_timeline_until_a_short_page() -> None:
    bundle = fixture("copilot-pull")
    github = Recorded(bundle)
    full = [{"event": "committed", "id": n} for n in range(100)]
    base = f"/repos/{REPO}/issues/46/timeline?per_page=100"
    github.served[f"{base}&page=1"] = (200, {"items": full})
    github.served[f"{base}&page=2"] = (200, {"items": bundle["timeline"]})

    assert read(github, REPO, 46)["timeline"] == full + bundle["timeline"]


def test_a_refused_read_raises_naming_the_status_and_path() -> None:
    with pytest.raises(OSError, match=r"HTTP 404.*pulls/46"):
        read(Recorded(), REPO, 46)


def log_of(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


def logged(log: EventLog) -> list[tuple[str, str, str | None, str | None]]:
    return [
        (e.fields["machine"], e.fields["event"], e.fields.get("task"), e.fields.get("run"))
        for e in Tail(log, "machine:events").poll()
    ]


def test_a_poll_appends_each_listed_pull_requests_events_and_a_second_poll_appends_none(tmp_path: Path) -> None:
    github, log = Recorded(fixture("copilot-pull"), fixture("reviewed-pull")), log_of(tmp_path)

    poll(github, REPO, adapter(), log, {})
    first = logged(log)
    poll(github, REPO, adapter(), log, {})

    assert len(first) == 7 + 5
    assert logged(log) == first
    assert {run for *_, run in first} == {f"{REPO}#46", f"{REPO}#38"}


def test_a_poll_reads_a_closed_pull_request_once_until_it_is_updated_but_an_open_one_every_time(tmp_path: Path) -> None:
    github = Recorded(fixture("copilot-pull"), fixture("reviewed-pull"))
    seen: dict[int, str] = {}

    poll(github, REPO, adapter(), log_of(tmp_path), seen)
    github.calls.clear()
    poll(github, REPO, adapter(), log_of(tmp_path), seen)

    assert [c for c in github.calls if "/pulls/" in c and c.endswith(("/46", "/38"))] == [f"/repos/{REPO}/pulls/46"]


class _Array(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps([{"id": 1}, {"id": 2}]).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def test_the_transport_hands_an_array_body_back_as_items(monkeypatch: pytest.MonkeyPatch) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Array)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("GITHUB_API_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        assert connect(None)("GET", "/anything", None) == (200, {"items": [{"id": 1}, {"id": 2}]})
    finally:
        server.shutdown()
