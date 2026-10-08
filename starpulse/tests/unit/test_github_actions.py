"""The GitHub Actions adapter: workflows, jobs and steps from the REST API, as `Dag` records."""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from starpulse.adapters.runs import run_events
from starpulse.adapters.runs.github_actions import (
    _CONCLUSION,
    _STATUS,
    GitHubRuns,
    declares_dispatch,
    listing,
    start,
    starter,
    status_of,
    workflow_run_entry,
)
from starpulse.adapters.runs.github_actions import follow as follow_repository
from starpulse.api.adapter_kit import RunsAdapterKit, serve, url
from starpulse.contracts.adapters import StartFailedError, TaskKeys
from starpulse.projections.board_feed import BoardFeed
from starpulse.settings.config import runs_adapter
from starpulse.store.event_log import EventLog
from starpulse.tests.github_stub import REPO, Recorded

#: Every status and conclusion GitHub documents for a run, job or step, plus `startup_failure` its webhooks and API
#: report; each with the status it becomes. A label GitHub adds later is not here, so the mapping must refuse it.
OPEN = {
    "requested": "queued",
    "pending": "queued",
    "queued": "queued",
    "waiting": "queued",
    "in_progress": "running",
}
CONCLUDED = {
    "success": "succeeded",
    "neutral": "succeeded",
    "failure": "failed",
    "timed_out": "failed",
    "startup_failure": "failed",
    "cancelled": "aborted",
    "stale": "aborted",
    "action_required": "aborted",
    "skipped": "skipped",
}


class TestGitHubActionsAdapter(RunsAdapterKit):
    """The adapter is a repository in, `Dag` records out; Actions has no task keys, so any scheme and branch examples do."""

    keys = TaskKeys(key=re.compile(r"PROJ-\d+"), branch=re.compile(r"feature/(PROJ-\d+)"))
    branches = {"feature/PROJ-1": "PROJ-1", "main": None}

    def produce(self) -> list[dict]:
        return listing(Recorded(runs={"ci": "ci-success"}), REPO)[0]


def listed(**stub) -> dict[str, dict]:
    """The recorded repository's workflows as the adapter lists them, by name."""
    return {dag["name"]: dag for dag in listing(Recorded(**stub), REPO)[0]}


def test_every_status_and_conclusion_maps_onto_the_enum_by_name() -> None:
    assert {s: status_of(s, None) for s in OPEN} == OPEN
    assert {c: status_of("completed", c) for c in CONCLUDED} == CONCLUDED
    assert (set(_STATUS), set(_CONCLUSION)) == (set(OPEN), set(CONCLUDED))


@pytest.mark.parametrize(
    ("status", "conclusion"),
    [("paused", None), ("completed", "exploded"), ("completed", None), ("in_progress", "success")],
)
def test_a_label_the_mapping_lacks_is_an_error_never_read_as_a_failure(status: str, conclusion: str | None) -> None:
    with pytest.raises(ValueError, match="unmapped"):
        status_of(status, conclusion)


def test_each_workflow_is_named_for_its_file_and_carries_its_latest_run() -> None:
    dag = listed()
    assert list(dag) == ["ci.yml", "release.yml", "ui-preview.yml"]
    assert (dag["ci.yml"]["status"], dag["ci.yml"]["runId"], dag["ci.yml"]["finishedAt"]) == (
        "queued",
        "37517391837",
        "",
    )
    cancelled = dag["ui-preview.yml"]
    assert (cancelled["status"], cancelled["raw"], cancelled["runId"]) == ("aborted", "cancelled", "37509741664")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", cancelled["finishedAt"])


def test_a_workflows_jobs_are_its_steps_waiting_on_the_jobs_they_need() -> None:
    dag = listed()
    assert [(s["name"], s["depends"], s["status"]) for s in dag["release.yml"]["steps"]] == [
        ("build", [], "queued"),
        ("github-release", ["build"], "not_started"),
        ("pypi", ["github-release"], "not_started"),
    ]
    ran = {s["name"]: (s["depends"], s["status"], s.get("raw")) for s in dag["ui-preview.yml"]["steps"]}
    assert ran == {
        "Render UI paths": ([], "aborted", "cancelled"),
        "Scan the demos for leaks": (["Render UI paths"], "skipped", None),
    }


def test_a_jobs_run_steps_follow_it_in_order_named_for_their_job() -> None:
    steps = listed(runs={"ci": "ci-success"})["ci.yml"]["steps"]
    python = [s for s in steps if s["name"].startswith("python / ")]
    assert [s["name"] for s in python][:3] == ["python / Set up job", "python / Set up runner", python[2]["name"]]
    assert python[0]["depends"] == ["python"]
    assert all(b["depends"] == [a["name"]] for a, b in zip(python, python[1:], strict=False))
    assert {s["status"] for s in steps} == {"succeeded"}


def job(name: str, status: str, conclusion: str | None = None, *, job_id: int = 1) -> dict:
    return {"id": job_id, "name": name, "status": status, "conclusion": conclusion, "steps": []}


def serving_jobs(*jobs: dict) -> dict:
    """The CI run's jobs replaced by `jobs`."""
    return {f"/repos/{REPO}/actions/runs/37517391837/jobs?per_page=100": (200, {"jobs": list(jobs)})}


def test_a_disabled_workflow_is_not_listed() -> None:
    workflows = Recorded()._served[f"/repos/{REPO}/actions/workflows?per_page=100"][1]
    off = {"workflows": [{**w, "state": "disabled_manually"} if w["path"].endswith("release.yml") else w for w in workflows["workflows"]]}
    assert list(listed(overrides={f"/repos/{REPO}/actions/workflows?per_page=100": (200, off)})) == [
        "ci.yml",
        "ui-preview.yml",
    ]


def test_a_workflow_with_no_file_lists_from_its_run_alone_and_leaves_the_others_listed() -> None:
    """GitHub-managed dynamic workflows (`dynamic/dependabot/update-graph`) have a path that is not a file."""
    gone = {f"/repos/{REPO}/contents/.github/workflows/ci.yml": (404, {})}
    github = Recorded(runs={"ci": "ci-success"}, overrides=gone)
    dags, startable = listing(github, REPO)
    assert [dag["name"] for dag in dags] == ["ci.yml", "release.yml", "ui-preview.yml"]
    ci = next(dag for dag in dags if dag["name"] == "ci.yml")
    assert ci["runId"] and {step["name"] for step in ci["steps"]} >= {"python", "web"}
    assert "ci.yml" not in startable


def test_a_workflow_that_never_ran_is_not_started_with_every_job_not_started() -> None:
    never = {f"/repos/{REPO}/actions/workflows/374969302/runs?per_page=1": (200, {"workflow_runs": []})}
    release = listed(overrides=never)["release.yml"]
    assert (release["status"], release["runId"], release["startedAt"], release["finishedAt"]) == ("not_started", "", "", "")
    assert {s["status"] for s in release["steps"]} == {"not_started"}


def test_a_matrix_job_is_the_worst_of_its_cells_and_a_job_the_file_lacks_joins_the_graph() -> None:
    cells = serving_jobs(
        job("python (3.13)", "completed", "success", job_id=1),
        job("python (3.14)", "completed", "failure", job_id=2),
        job("web", "in_progress", job_id=3),
        job("shared / lint", "queued", job_id=4),
    )
    steps = {s["name"]: s for s in listed(overrides=cells)["ci.yml"]["steps"]}
    assert {name: (s["depends"], s["status"]) for name, s in steps.items()} == {
        "python": ([], "failed"),
        "web": ([], "running"),
        "shared / lint": ([], "queued"),
    }


@pytest.mark.parametrize(
    ("on", "dispatches"),
    [
        ("workflow_dispatch", True),
        ("[push, workflow_dispatch]", True),
        ("{push: null, workflow_dispatch: {inputs: {x: {}}}}", True),
        ("\n  push:\n  workflow_dispatch:", True),
        ("push", False),
        ("[push, pull_request]", False),
        ("{push: {branches: [main]}}", False),
        ("{workflow_call: null}", False),
    ],
)
def test_a_workflow_dispatches_when_its_on_names_workflow_dispatch_in_any_of_yamls_three_shapes(
    on: str, dispatches: bool
) -> None:
    assert declares_dispatch(yaml.safe_load(f"on: {on}\njobs: {{}}")) is dispatches


def test_a_file_with_no_trigger_or_a_nonsense_one_does_not_dispatch() -> None:
    assert [declares_dispatch(d) for d in ({}, {"jobs": {}}, {True: 7}, {True: None})] == [False] * 4


def test_the_listing_reports_the_workflows_that_declare_workflow_dispatch_as_startable() -> None:
    _, startable = listing(Recorded(), REPO)
    assert startable == ["ui-preview.yml"]


def dispatched(answer=(200, {"workflow_run_id": 9001}), **stub) -> tuple[Recorded, str | StartFailedError]:
    """Start `ui-preview.yml` against a GitHub answering the dispatch with `answer`: the calls, and the run id or the refusal."""
    github = Recorded(dispatch=lambda body: answer, **stub)
    try:
        return github, starter(github, REPO)("ui-preview.yml")
    except StartFailedError as exc:
        return github, exc


def test_a_start_dispatches_on_the_default_branch_and_answers_the_run_id() -> None:
    github, run_id = dispatched()
    assert run_id == "9001"
    assert [(m, p, b) for m, p, b in github.calls if m == "POST"] == [
        (
            "POST",
            f"/repos/{REPO}/actions/workflows/ui-preview.yml/dispatches",
            {"ref": "main", "return_run_details": True},
        )
    ]


def test_a_start_of_a_workflow_without_workflow_dispatch_is_refused_before_any_dispatch() -> None:
    github = Recorded()
    with pytest.raises(StartFailedError, match=r"ci\.yml.*workflow_dispatch"):
        starter(github, REPO)("ci.yml")
    assert github.paths("POST") == []


def test_a_workflow_the_repository_lacks_is_a_refused_start() -> None:
    with pytest.raises(StartFailedError, match=r"no workflow nightly\.yml"):
        starter(Recorded(), REPO)("nightly.yml")


@pytest.mark.parametrize(("code", "reason"), [(403, "HTTP 403"), (404, "HTTP 404"), (422, "HTTP 422")])
def test_a_dispatch_github_refuses_is_a_refused_start_naming_its_status(code: int, reason: str) -> None:
    _, refusal = dispatched((code, {}))
    assert isinstance(refusal, StartFailedError) and reason in str(refusal)


def test_a_dispatch_github_accepts_without_a_run_id_answers_an_empty_run_id() -> None:
    assert dispatched((204, {}))[1] == ""


def test_an_instance_can_start_runs_only_with_a_token_in_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert start("trantor-org/starpulse") is None
    monkeypatch.setenv("GH_TOKEN", "t")
    assert callable(start("https://github.com/trantor-org/starpulse.git"))


def post_run(server, workflow: str) -> tuple[int, dict]:
    """What the page's Run now button gets: the status and body of `POST /api/run/<workflow>`."""
    request = urllib.request.Request(
        url(server, f"/api/run/{workflow}"), data=b"", method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def test_run_now_starts_a_workflow_that_declares_workflow_dispatch_and_is_absent_from_one_that_does_not(tmp_path) -> None:
    github = Recorded(dispatch=lambda body: (200, {"workflow_run_id": 9001}))
    names = ("gh/ci.yml", "gh/ui-preview.yml")
    feed = BoardFeed(domains={"CI": names}, run_safe=names)
    GitHubRuns(feed.runs("gh"), lambda only=None: listing(github, REPO, only)).reconcile()

    with serve(tmp_path, feed, starts={"gh": starter(github, REPO)}, run_safe=frozenset(names)) as server:
        flags = {d["name"]: d["runSafe"] for d in feed.snapshot()["domains"][0]["dags"]}
        assert flags == {"gh/ci.yml": False, "gh/ui-preview.yml": True}
        assert post_run(server, "gh/ui-preview.yml") == (200, {"runId": "9001"})
        status, body = post_run(server, "gh/ci.yml")
    assert status == 502 and "workflow_dispatch" in body["error"]


def test_a_listing_of_named_workflows_reads_only_those_and_reports_only_their_dispatch() -> None:
    dags, startable = listing(Recorded(), REPO, only={"ui-preview.yml"})
    assert ([d["name"] for d in dags], startable) == (["ui-preview.yml"], ["ui-preview.yml"])
    assert listing(Recorded(), REPO, only={"ci.yml"})[1] == []


def test_the_config_type_github_actions_names_a_runs_adapter() -> None:
    assert runs_adapter("github_actions").__name__ == "starpulse.adapters.runs.github_actions"


LISTED_AT = 100.0


class Followed:
    """A `GitHubRuns` over a repository whose state a test swaps, listed at `LISTED_AT`, and the feed it draws on."""

    def __init__(self) -> None:
        self.github = Recorded()
        self.feed = BoardFeed(
            domains={"CI": ("gh/ci.yml", "gh/release.yml", "gh/ui-preview.yml")},
            run_safe=("gh/ci.yml", "gh/release.yml", "gh/ui-preview.yml"),
        )
        self.runs = GitHubRuns(
            self.feed.runs("gh"), lambda only=None: listing(self.github, REPO, only), clock=lambda: LISTED_AT
        )
        self.runs.reconcile()
        self.github = Recorded(runs={"ci": "ci-success"})  # CI has since succeeded

    def entry(self, workflow: str, *, at: float = LISTED_AT + 1, **fields) -> None:
        sent = run_events.entry("end", workflow, "1", "succeeded", now=at) | fields
        self.runs.handle_entry("1-0", sent)

    def status(self, workflow: str) -> str:
        return next(d["status"] for d in self.feed.snapshot()["dags"] if d["name"] == f"gh/{workflow}")


def test_an_entry_for_a_workflow_reads_that_workflow_again_and_moves_it_alone() -> None:
    run = Followed()
    run.entry("ci.yml")
    assert run.status("ci.yml") == "succeeded"
    assert not any("/374969302/" in p or "/375863838/" in p for p in run.github.paths())


def test_an_entry_leaves_the_workflows_that_may_run_now_as_the_listing_found_them() -> None:
    run = Followed()
    run.entry("ci.yml")
    flags = {d["name"]: d["runSafe"] for d in run.feed.snapshot()["domains"][0]["dags"]}
    assert flags == {"gh/ci.yml": False, "gh/release.yml": False, "gh/ui-preview.yml": True}


@pytest.mark.parametrize(
    "entry",
    [
        {"workflow": "ci.yml", "at": LISTED_AT - 1},  # already in the listing
        {"workflow": "nightly.yml"},  # a workflow the repository did not list
        {"workflow": "ci.yml", "status": "exploded"},  # not the contract's
        {"workflow": "ci.yml", "phase": "middle"},
    ],
)
def test_an_entry_the_listing_already_holds_or_the_contract_does_not_allow_asks_github_nothing(entry: dict) -> None:
    run = Followed()
    run.entry(entry.pop("workflow"), **entry)
    assert (run.github.calls, run.status("ci.yml")) == ([], "queued")


def test_a_listing_github_cannot_serve_after_an_entry_keeps_what_the_page_had() -> None:
    run = Followed()
    run.github = Recorded(overrides={f"/repos/{REPO}/actions/workflows?per_page=100": (500, {})})
    run.entry("ci.yml")
    assert (run.status("ci.yml"), run.feed.snapshot()["error"]) == ("queued", None)


def test_a_github_that_goes_unreachable_keeps_the_workflows_last_read_and_reports_the_error() -> None:
    run = Followed()
    run.github = Recorded(overrides={f"/repos/{REPO}/actions/workflows?per_page=100": (403, {})})
    run.runs.reconcile()
    assert run.status("ci.yml") == "queued"
    assert "HTTP 403" in run.feed.snapshot()["error"]


def test_a_workflow_file_that_is_not_yaml_is_an_unreadable_response_not_a_crash() -> None:
    run = Followed()
    broken = {"content": "b246IFtwdXNoCmpvYnM6IHsK"}  # base64 of a file with unclosed brackets
    run.github = Recorded(overrides={f"/repos/{REPO}/contents/.github/workflows/ci.yml": (200, broken)})
    run.runs.reconcile()
    assert run.feed.snapshot()["error"].startswith("gh: unreadable response (")


WEBHOOK = {
    "action": "completed",
    "workflow_run": {
        "id": 37517391837,
        "path": ".github/workflows/ci.yml",
        "status": "completed",
        "conclusion": "success",
        "updated_at": "2026-07-01T12:00:00Z",
    },
}
AT = datetime(2026, 7, 1, 12, tzinfo=UTC).timestamp()


def hook(**run) -> dict:
    return {**WEBHOOK, "workflow_run": {**WEBHOOK["workflow_run"], **run}}


@pytest.mark.parametrize(
    ("run", "expected"),
    [
        ({}, ("end", "succeeded")),
        ({"status": "in_progress", "conclusion": None}, ("start", "running")),
        ({"status": "queued", "conclusion": None}, ("start", "queued")),
        ({"conclusion": "cancelled"}, ("end", "aborted")),
        ({"path": ".github/workflows/ci.yml@refs/heads/main"}, ("end", "succeeded")),
    ],
)
def test_a_workflow_run_webhook_becomes_the_stream_entry_for_its_workflow_file(run: dict, expected: tuple) -> None:
    assert workflow_run_entry(hook(**run)) == run_events.entry(
        expected[0], "ci.yml", "37517391837", expected[1], now=AT
    )


def test_a_workflow_run_webhook_with_a_status_the_mapping_lacks_is_refused() -> None:
    with pytest.raises(ValueError, match="unmapped"):
        workflow_run_entry(hook(status="paused", conclusion=None))


def wait_until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not met within the timeout"
        time.sleep(0.01)


def test_following_a_repository_lists_it_then_moves_a_workflow_by_the_entries_on_the_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("starpulse.adapters.runs.github_actions._reconcile_forever", lambda runs: None)  # only the entries move it
    served = [Recorded()]
    monkeypatch.setattr("starpulse.adapters.runs.github_actions.connect", lambda token: lambda *call: served[0](*call))
    started: list[threading.Thread] = []
    real_start = threading.Thread.start
    monkeypatch.setattr(threading.Thread, "start", lambda self: (started.append(self), real_start(self))[1])
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    feed = BoardFeed()

    follow_repository(f"https://github.com/{REPO}", feed.runs("gh"), log, interval=0.01)
    wait_until(lambda: feed.snapshot()["dags"])
    served[0] = Recorded(runs={"ci": "ci-success"})
    log.append(run_events.STREAM, run_events.entry("end", "ci.yml", "1", "succeeded", now=time.time() + 60))
    wait_until(lambda: next(d for d in feed.snapshot()["dags"] if d["name"] == "gh/ci.yml")["status"] == "succeeded")

    assert [(t.name, t.daemon) for t in started if t.name.startswith("github-")] == [
        ("github-runs", True),
        ("github-runs-reconcile", True),
    ]
