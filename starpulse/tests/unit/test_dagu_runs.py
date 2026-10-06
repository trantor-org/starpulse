"""The Dagu adapter: each DAG's latest run, from one Dagu listing and then the `runs:events` entries."""

from __future__ import annotations

import json
import queue
import re
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from starpulse import run_events
from starpulse.adapter_kit import RunsAdapterKit
from starpulse.board_feed import BoardFeed
from starpulse.contracts import StartFailedError, TaskKeys
from starpulse.dagu import _STATUS, DaguRuns, Transport, connect, dags, pools, start, starter, status_of
from starpulse.dagu import follow as follow_instance
from starpulse.event_log import EventLog
from starpulse.tests.dagu_stub import InFlight, Queue, dagu, run_entry

LISTING = "/api/v1/dags?perPage=200"
#: The listing is read at this time; an entry stamped before it is already in the listing.
LISTED_AT = 100.0


class TestDaguAdapter(RunsAdapterKit):
    """The adapter is a Dagu URL in, `Dag` records out; Dagu has no task keys, so any scheme and branch examples do."""

    keys = TaskKeys(key=re.compile(r"PROJ-\d+"), branch=re.compile(r"feature/(PROJ-\d+)"))
    branches = {"feature/PROJ-1": "PROJ-1", "main": None}

    def produce(self) -> list[dict]:
        with self._serving() as (base_url, _):
            return dags(base_url)

    def produce_pools(self) -> list[dict]:
        with self._serving() as (base_url, _):
            return pools(base_url)

    @staticmethod
    def _serving():
        """A Dagu with `deliver` running twice and queued once on a two-run queue, and an idle DAG on no queue."""
        queues = {"deliver": Queue(2, 2, 1)}
        return dagu({**DELIVER, "d2": ["c"]}, **LANE, queues=queues, in_flight=(LINTING, WAITING, QUEUED))


DELIVER = {"deliver": ["refuse", "lint", "wait_ci"]}
LANE = {"queue_of": {"deliver": "deliver"}}
#: One run in `lint`, one further on in `wait_ci`, and one waiting for a slot on the `deliver` queue.
LINTING = InFlight(
    "deliver",
    "r1",
    started_at="2026-10-05T23:00:00Z",
    nodes=(
        ("refuse", "succeeded", "2026-10-05T23:00:01Z"),
        ("lint", "running", "2026-10-05T23:00:02Z"),
        ("wait_ci", "not_started", ""),
    ),
)
WAITING = InFlight(
    "deliver",
    "r2",
    started_at="2026-10-05T23:04:00Z",
    nodes=(
        ("refuse", "succeeded", "2026-10-05T23:04:01Z"),
        ("lint", "succeeded", "2026-10-05T23:04:02Z"),
        ("wait_ci", "running", "2026-10-05T23:04:30Z"),
    ),
)
QUEUED = InFlight(
    "deliver",
    "r3",
    label="queued",
    queued_at="2026-10-05T23:05:00Z",
    nodes=(("refuse", "not_started", ""), ("lint", "not_started", ""), ("wait_ci", "not_started", "")),
)


def deliver(*, in_flight: tuple[InFlight, ...], **stub) -> dict:
    """The `deliver` DAG as the adapter lists it while Dagu runs `in_flight`."""
    with dagu(DELIVER, **LANE, in_flight=in_flight, **stub) as (base_url, _):
        return next(d for d in dags(base_url) if d["name"] == "deliver")


def follow(base_url: str) -> tuple[BoardFeed, DaguRuns, queue.Queue]:
    """A runs reader that has taken its one listing, and the queue of changes a page would get."""
    feed = BoardFeed()
    runs = DaguRuns(
        feed.runs("ci"), lambda only=None: dags(base_url, only), lambda: pools(base_url), clock=lambda: LISTED_AT
    )
    runs.reconcile()
    _, changes = feed.subscribe()
    return feed, runs, changes


def dag(feed: BoardFeed, name: str) -> dict:
    return next(d for d in feed.snapshot()["dags"] if d["name"] == f"ci/{name}")


def statuses(feed: BoardFeed, name: str) -> dict[str, str]:
    return {s["name"]: s["status"] for s in dag(feed, name)["steps"]}


def test_the_listing_gives_each_dag_its_step_graph() -> None:
    with dagu({"d1": ["a", "b"]}) as (base_url, _):
        feed, _, _ = follow(base_url)

    assert [(s["name"], s["depends"]) for s in dag(feed, "d1")["steps"]] == [("a", []), ("b", ["a"])]


def test_a_start_entry_marks_the_dag_running_with_its_steps_not_started_and_pushes_it() -> None:
    with dagu({"d1": ["a", "b"], "d2": ["c"]}) as (base_url, _):
        feed, runs, changes = follow(base_url)

        runs.handle_entry(*run_entry("start", "d1", "r1", "running", at=101.0))

    d1 = dag(feed, "d1")
    assert (d1["status"], d1["runId"], d1["startedAt"], d1["finishedAt"]) == (
        "running",
        "r1",
        "1970-01-01T00:01:41Z",
        "",
    )
    assert statuses(feed, "d1") == {"a": "not_started", "b": "not_started"}
    assert statuses(feed, "d2") == {"c": "succeeded"}
    kind, delta = changes.get_nowait()
    assert (kind, [d["status"] for d in delta["dags"]]) == ("dags", ["running", "succeeded"])


def test_an_end_entry_sets_the_terminal_status_and_reads_each_steps_status_from_dagu() -> None:
    labels: dict[str, str] = {}
    with dagu({"d1": ["a", "b"]}, labels) as (base_url, calls):
        feed, runs, _ = follow(base_url)
        runs.handle_entry(*run_entry("start", "d1", "r1", "running", at=101.0))
        labels["b"] = "failed"
        calls.clear()

        runs.handle_entry(*run_entry("end", "d1", "r1", "failed", at=105.0))

    d1 = dag(feed, "d1")
    assert (d1["status"], d1["finishedAt"]) == ("failed", "1970-01-01T00:01:45Z")
    assert statuses(feed, "d1") == {"a": "succeeded", "b": "failed"}
    assert calls == [LISTING, "/api/v1/dags/d1"]


def test_an_end_entry_keeps_the_step_statuses_the_dag_had_when_dagu_cannot_be_read() -> None:
    feed = BoardFeed()
    step = {"name": "a", "depends": [], "status": "succeeded", "kind": None}
    listed = [{"name": "d1", "status": "succeeded", "runId": "r0", "startedAt": "", "finishedAt": "", "steps": [step]}]
    answers: list = [listed, OSError("refused")]

    def fetch(only: object = None) -> list:
        answer = answers.pop(0)
        if isinstance(answer, OSError):
            raise answer
        return answer

    runs = DaguRuns(feed.runs("ci"), fetch, clock=lambda: LISTED_AT)
    runs.reconcile()

    runs.handle_entry(*run_entry("end", "d1", "r0", "failed", at=105.0))

    assert (dag(feed, "d1")["status"], statuses(feed, "d1")) == ("failed", {"a": "succeeded"})


def test_the_end_of_a_run_that_is_neither_the_one_drawn_nor_an_active_one_changes_nothing() -> None:
    with dagu({"d1": ["a"]}) as (base_url, _):
        feed, runs, changes = follow(base_url)
        runs.handle_entry(*run_entry("start", "d1", "r1", "running", at=101.0))
        runs.handle_entry(*run_entry("start", "d1", "r2", "running", at=102.0))
        while not changes.empty():
            changes.get_nowait()

        runs.handle_entry(*run_entry("end", "d1", "r0", "failed", at=103.0))

    assert (dag(feed, "d1")["status"], dag(feed, "d1")["runId"]) == ("running", "r2")
    assert changes.empty()


def test_an_entry_from_before_the_listing_is_already_in_it_and_changes_nothing() -> None:
    with dagu({"d1": ["a"]}) as (base_url, _):
        feed, runs, changes = follow(base_url)

        runs.handle_entry(*run_entry("start", "d1", "r1", "running", at=LISTED_AT - 1))

    assert dag(feed, "d1")["status"] == "succeeded"
    assert changes.empty()


def test_a_malformed_entry_is_dropped() -> None:
    with dagu({"d1": ["a"]}) as (base_url, _):
        feed, runs, changes = follow(base_url)

        runs.handle_entry("9-0", {"workflow": "d1", "phase": "start", "time": "soon"})
        runs.handle_entry("9-1", {"workflow": "d1", "phase": "paused", "time": "101.0", "run_id": "r1"})

    assert dag(feed, "d1")["status"] == "succeeded"
    assert changes.empty()


def test_a_start_costs_dagu_nothing_and_an_end_one_listing_and_that_dags_step_read() -> None:
    with dagu({"d1": ["a", "b"], "d2": ["c"]}) as (base_url, calls):
        feed, runs, _ = follow(base_url)
        calls.clear()

        for n in range(1, 21):
            runs.handle_entry(*run_entry("start", "d1", f"r{n}", "running", at=LISTED_AT + 2 * n))
        assert calls == []

        runs.handle_entry(*run_entry("end", "d1", "r20", "succeeded", at=LISTED_AT + 50))

    assert calls == [LISTING, "/api/v1/dags/d1"]
    assert dag(feed, "d1")["runId"] == "r20"


def test_a_run_of_a_dag_the_listing_lacks_triggers_one_more_listing() -> None:
    steps = {"d1": ["a"]}
    with dagu(steps) as (base_url, calls):
        feed, runs, _ = follow(base_url)
        steps["d3"] = ["x", "y"]

        runs.handle_entry(*run_entry("start", "d3", "r1", "running", at=101.0))

    assert calls.count(LISTING) == 2
    assert (dag(feed, "d3")["status"], statuses(feed, "d3")) == ("running", {"x": "not_started", "y": "not_started"})


def test_a_dagu_that_goes_unreachable_keeps_the_dags_it_last_had_and_reports_the_error() -> None:
    feed = BoardFeed()
    listed = [{"name": "d1", "status": "succeeded", "runId": "", "startedAt": "", "finishedAt": "", "steps": []}]
    answers: list = [listed, OSError("refused")]

    def fetch(only: object = None) -> list:
        answer = answers.pop(0)
        if isinstance(answer, OSError):
            raise answer
        return answer

    runs = DaguRuns(feed.runs("ci"), fetch, clock=lambda: LISTED_AT)
    runs.reconcile()

    runs.reconcile()

    assert ([d["name"] for d in feed.snapshot()["dags"]], feed.snapshot()["error"]) == (["ci/d1"], "ci: refused")


@pytest.mark.parametrize(
    "failure", [json.JSONDecodeError("Expecting value", "<html>", 0), KeyError("fileName"), TypeError("not a dict")]
)
def test_a_dagu_answer_that_does_not_parse_keeps_the_dags_and_reports_the_error(failure: Exception) -> None:
    """The consumer thread must outlive one bad listing."""
    feed = BoardFeed()
    listed = [{"name": "d1", "status": "succeeded", "runId": "", "startedAt": "", "finishedAt": "", "steps": []}]
    answers: list = [listed, failure]

    def fetch(only: object = None) -> list:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    runs = DaguRuns(feed.runs("ci"), fetch, clock=lambda: LISTED_AT)
    runs.reconcile()

    runs.reconcile()

    body = feed.snapshot()
    assert [d["name"] for d in body["dags"]] == ["ci/d1"]
    assert body["error"].startswith("ci: unreadable response") and type(failure).__name__ in body["error"]


def test_a_dagu_that_was_down_at_the_listing_is_read_again_when_a_run_arrives() -> None:
    feed = BoardFeed()
    answers: list = [
        OSError("refused"),
        [{"name": "d1", "status": "succeeded", "runId": "", "startedAt": "", "finishedAt": "", "steps": []}],
    ]

    def fetch(only: object = None) -> list:
        answer = answers.pop(0)
        if isinstance(answer, OSError):
            raise answer
        return answer

    runs = DaguRuns(feed.runs("ci"), fetch, clock=lambda: LISTED_AT)
    runs.reconcile()
    assert (feed.snapshot()["dags"], feed.snapshot()["error"]) == ([], "ci: refused")

    runs.handle_entry(*run_entry("start", "d1", "r1", "running", at=101.0))

    assert (dag(feed, "d1")["status"], feed.snapshot()["error"]) == ("running", None)


def test_a_start_clears_the_finish_time_the_listing_gave_the_dag() -> None:
    feed = BoardFeed()
    done = "2020-01-01T00:00:00Z"
    listed = [{"name": "d1", "status": "failed", "runId": "r0", "startedAt": "", "finishedAt": done, "steps": []}]
    runs = DaguRuns(feed.runs("ci"), lambda only=None: listed, clock=lambda: LISTED_AT)
    runs.reconcile()

    runs.handle_entry(*run_entry("start", "d1", "r1", "running", at=101.0))

    assert dag(feed, "d1")["finishedAt"] == ""


def test_an_entry_is_applied_before_any_listing_has_been_taken() -> None:
    feed = BoardFeed()
    listed = [{"name": "d1", "status": "succeeded", "runId": "", "startedAt": "", "finishedAt": "", "steps": []}]
    runs = DaguRuns(feed.runs("ci"), lambda only=None: listed, clock=lambda: 0.0)

    runs.handle_entry(*run_entry("start", "d1", "r1", "running", at=0.5))

    assert dag(feed, "d1")["status"] == "running"


def test_an_entry_stamped_at_the_moment_of_the_listing_is_applied() -> None:
    with dagu({"d1": ["a"]}) as (base_url, _):
        feed, runs, _ = follow(base_url)

        runs.handle_entry(*run_entry("start", "d1", "r1", "running", at=LISTED_AT))

    assert dag(feed, "d1")["status"] == "running"


def test_a_relist_that_postdates_the_entry_drops_it() -> None:
    feed = BoardFeed()
    now = iter([50.0, 200.0])
    listed = [{"name": "d1", "status": "succeeded", "runId": "", "startedAt": "", "finishedAt": "", "steps": []}]
    runs = DaguRuns(feed.runs("ci"), lambda only=None: listed, clock=lambda: next(now))
    runs.reconcile()
    listed.append({"name": "d2", "status": "succeeded", "runId": "", "startedAt": "", "finishedAt": "", "steps": []})

    runs.handle_entry(*run_entry("start", "d2", "r1", "running", at=100.0))

    assert dag(feed, "d2")["status"] == "succeeded"


def test_an_entry_stamped_at_the_moment_of_the_relist_is_applied() -> None:
    feed = BoardFeed()
    now = iter([50.0, 200.0])
    listed = [{"name": "d1", "status": "succeeded", "runId": "", "startedAt": "", "finishedAt": "", "steps": []}]
    runs = DaguRuns(feed.runs("ci"), lambda only=None: listed, clock=lambda: next(now))
    runs.reconcile()
    listed.append({"name": "d2", "status": "succeeded", "runId": "", "startedAt": "", "finishedAt": "", "steps": []})

    runs.handle_entry(*run_entry("start", "d2", "r1", "running", at=200.0))

    assert dag(feed, "d2")["status"] == "running"


def test_an_entry_for_a_dag_nobody_lists_changes_nothing() -> None:
    with dagu({"d1": ["a"]}) as (base_url, _):
        feed, runs, changes = follow(base_url)

        runs.handle_entry(*run_entry("start", "ghost", "r1", "running", at=101.0))

    assert [d["name"] for d in feed.snapshot()["dags"]] == ["ci/d1"]
    assert changes.empty()


def test_an_entry_about_a_step_changes_nothing() -> None:
    with dagu({"d1": ["a"]}) as (base_url, _):
        feed, runs, changes = follow(base_url)
        entry = run_entry("start", "d1", "r1", "running", at=101.0)[1] | {"step": "a"}

        runs.handle_entry("9-0", entry)

    assert dag(feed, "d1")["status"] == "succeeded"
    assert changes.empty()


def test_an_entry_missing_a_field_is_dropped() -> None:
    with dagu({"d1": ["a"]}) as (base_url, _):
        feed, runs, changes = follow(base_url)
        whole = {"workflow": "d1", "phase": "start", "time": "101.0", "run_id": "r1", "status": "running"}

        for missing in whole:
            runs.handle_entry("9-0", {k: v for k, v in whole.items() if k != missing})

    assert dag(feed, "d1")["status"] == "succeeded"
    assert changes.empty()


class _Reply:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode()

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, *_: object) -> bytes:
        return self._body


def test_a_dag_carries_its_step_edges_each_steps_latest_status_and_declared_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = json.loads((Path(__file__).parents[1] / "fixtures" / "dagu_alert_investigation.json").read_text())
    listing = {"dags": [{"fileName": "alert-investigation", "latestDAGRun": detail["latestDAGRun"]}]}
    asked: list[str] = []

    def urlopen(url: str, timeout: float) -> _Reply:
        asked.append(url)
        return _Reply(detail if url.endswith("/dags/alert-investigation") else listing)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    (dag,) = dags("http://dagu")

    assert dag["steps"] == [
        {"name": "ack", "depends": [], "status": "succeeded", "kind": "code"},
        {"name": "triage", "depends": ["ack"], "status": "succeeded", "kind": "code"},
        {"name": "investigate", "depends": ["triage"], "status": "running", "kind": "agent"},
        {"name": "reason", "depends": ["investigate"], "status": "not_started", "kind": "code"},
        {"name": "remediate", "depends": ["reason"], "status": "not_started", "kind": "code"},
        {"name": "fix", "depends": ["remediate"], "status": "not_started", "kind": "agent"},
        {"name": "finalize", "depends": ["fix"], "status": "not_started", "kind": "code"},
    ]
    assert asked[-1] == "http://dagu/api/v1/dags/alert-investigation"


def test_dags_reads_each_dags_latest_run_with_defaults_for_what_dagu_omits(monkeypatch: pytest.MonkeyPatch) -> None:
    listing = {
        "dags": [
            {
                "fileName": "ran",
                "latestDAGRun": {
                    "statusLabel": "failed",
                    "dagRunId": "r1",
                    "startedAt": "s",
                    "queuedAt": "q",
                    "finishedAt": "f",
                },
            },
            {"fileName": "queued", "latestDAGRun": {"statusLabel": "queued", "queuedAt": "q"}},
            {"fileName": "never"},
            {"fileName": "unlabelled", "latestDAGRun": {"statusLabel": ""}},
        ]
    }
    details = {
        "ran": {"dag": {"steps": [{"name": "only"}]}, "latestDAGRun": {"nodes": []}},
        "queued": {
            "dag": {"steps": [{"name": "a", "description": "prose, not a kind"}, {"name": "b", "depends": ["a"]}]},
            "latestDAGRun": None,
        },
        "never": {"dag": {}},
        "unlabelled": {
            "dag": {"steps": [{"name": "a"}]},
            "latestDAGRun": {"nodes": [{"step": {"name": "a"}, "statusLabel": "running"}]},
        },
    }
    timeouts: list[float] = []

    def urlopen(url: str, timeout: float) -> _Reply:
        timeouts.append(timeout)
        return _Reply(details[url.rsplit("/", 1)[1]] if "perPage" not in url else listing)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert dags("http://dagu") == [
        {
            "name": "ran",
            "status": "failed",
            "runId": "r1",
            "startedAt": "s",
            "finishedAt": "f",
            "steps": [{"name": "only", "depends": [], "status": "not_started", "kind": None}],
            "active": [],
            "pool": "",
        },
        {
            "name": "queued",
            "status": "queued",
            "runId": "",
            "startedAt": "q",
            "finishedAt": "",
            "steps": [
                {"name": "a", "depends": [], "status": "not_started", "kind": None},
                {"name": "b", "depends": ["a"], "status": "not_started", "kind": None},
            ],
            "active": [],
            "pool": "",
        },
        {
            "name": "never",
            "status": "not_started",
            "runId": "",
            "startedAt": "",
            "finishedAt": "",
            "steps": [],
            "active": [],
            "pool": "",
        },
        {
            "name": "unlabelled",
            "status": "not_started",
            "runId": "",
            "startedAt": "",
            "finishedAt": "",
            "steps": [{"name": "a", "depends": [], "status": "running", "kind": None}],
            "active": [],
            "pool": "",
        },
    ]
    assert set(timeouts) == {5}


def test_dags_asks_for_step_detail_only_of_the_dags_it_is_told_to_keep(monkeypatch: pytest.MonkeyPatch) -> None:
    listing = {"dags": [{"fileName": "kept"}, {"fileName": "dropped"}]}
    asked: list[str] = []

    def urlopen(url: str, timeout: float) -> _Reply:
        asked.append(url)
        return _Reply(listing if "perPage" in url else {"dag": {}})

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert [d["name"] for d in dags("http://dagu", only={"kept"})] == ["kept"]
    assert asked == ["http://dagu/api/v1/dags?perPage=200", "http://dagu/api/v1/dags/kept"]


def test_a_dag_left_out_does_not_end_the_listing_of_those_after_it(monkeypatch: pytest.MonkeyPatch) -> None:
    listing = {"dags": [{"fileName": "dropped"}, {"fileName": "kept"}]}

    def urlopen(url: str, timeout: float) -> _Reply:
        return _Reply(listing if "perPage" in url else {"dag": {}})

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert [d["name"] for d in dags("http://dagu", only={"kept"})] == ["kept"]


def test_a_dag_whose_detail_cannot_be_read_is_listed_without_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    listing = {"dags": [{"fileName": "broken"}, {"fileName": "fine"}]}

    def urlopen(url: str, timeout: float) -> _Reply:
        if url.endswith("/broken"):
            raise OSError("timed out")
        return _Reply(listing if "perPage" in url else {"dag": {"steps": [{"name": "a"}]}})

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert [(d["name"], [s["name"] for s in d["steps"]]) for d in dags("http://dagu")] == [
        ("broken", []),
        ("fine", ["a"]),
    ]


def test_dags_is_empty_when_dagu_lists_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: _Reply({}))

    assert dags("http://dagu") == []


#: Dagu's nine status labels (its v1 OpenAPI `StatusLabel` schema) and the closed-enum status each becomes.
DAGU_LABELS = {
    "not_started": "not_started",
    "running": "running",
    "failed": "failed",
    "aborted": "aborted",
    "succeeded": "succeeded",
    "queued": "queued",
    "partially_succeeded": "failed",  # a step failed and the run went on: not a success
    "waiting": "running",  # held for an approval: the run is still in flight
    "rejected": "aborted",  # an approval refused: the run was stopped, not failed by a step
}


def test_the_mapping_covers_every_status_label_dagu_reports() -> None:
    assert DAGU_LABELS.keys() == _STATUS.keys() - {"skipped"}  # `skipped` is a step label, not a run label


@pytest.mark.parametrize(("label", "status"), DAGU_LABELS.items())
def test_each_dagu_label_maps_to_its_enum_status_by_name_and_is_kept_as_raw_when_it_differs(
    monkeypatch: pytest.MonkeyPatch, label: str, status: str
) -> None:
    listing = {"dags": [{"fileName": "d", "latestDAGRun": {"statusLabel": label}}]}
    detail = {
        "dag": {"steps": [{"name": "a"}]},
        "latestDAGRun": {"nodes": [{"step": {"name": "a"}, "statusLabel": label}]},
    }
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: _Reply(listing if "perPage" in url else detail))
    raw = {"raw": label} if label != status else {}

    (listed,) = dags("http://dagu")

    assert (listed["status"], listed.get("raw")) == (status, raw.get("raw"))
    assert [(s["status"], s.get("raw")) for s in listed["steps"]] == [(status, raw.get("raw"))]


def test_a_skipped_step_is_skipped() -> None:
    assert status_of("skipped") == "skipped"


def test_a_label_dagu_adds_is_refused_by_name_rather_than_read_as_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    listing = {"dags": [{"fileName": "d", "latestDAGRun": {"statusLabel": "paused"}}]}
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda url, timeout: _Reply(listing if "perPage" in url else {"dag": {}})
    )

    with pytest.raises(ValueError, match="paused"):
        dags("http://dagu")


def test_an_end_entry_maps_each_steps_label_and_keeps_the_raw_one() -> None:
    labels = {"b": "rejected"}
    with dagu({"d1": ["a", "b"]}, labels) as (base_url, _):
        feed, runs, _ = follow(base_url)
        runs.handle_entry(*run_entry("start", "d1", "r1", "running", 101.0))
        runs.handle_entry(*run_entry("end", "d1", "r1", "failed", 105.0))

    assert (dag(feed, "d1")["status"], "raw" in dag(feed, "d1")) == ("failed", False)
    assert [(s["status"], s.get("raw")) for s in dag(feed, "d1")["steps"]] == [
        ("succeeded", None),
        ("aborted", "rejected"),
    ]


def test_an_end_entry_with_a_status_the_contract_lacks_is_dropped() -> None:
    with dagu({"d1": ["a"]}) as (base_url, _):
        feed, runs, _ = follow(base_url)
        runs.handle_entry(*run_entry("start", "d1", "r1", "running", 101.0))
        runs.handle_entry(*run_entry("end", "d1", "r1", "paused", 105.0))

    assert dag(feed, "d1")["status"] == "running"


def test_the_adapters_start_capability_is_the_starter_over_the_instances_url(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []

    def connect(url: str) -> Transport:
        return lambda method, path, body: sent.append((url, path)) or (200, {"dagRunId": "run-9"})

    monkeypatch.setattr("starpulse.dagu.connect", connect)

    assert start("http://dagu.test:8085")("healthcheck") == "run-9"
    assert sent == [("http://dagu.test:8085", "/dags/healthcheck/start")]


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


def _run_event(log: EventLog, phase: str, status: str, workflow: str = "d1", at: float | None = None) -> None:
    now = time.time() + 60 if at is None else at  # after any listing the test's follow takes
    log.append(run_events.STREAM, run_events.entry(phase, workflow, "r1", status, now=now))


def _wait_until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not met within the timeout"
        time.sleep(0.01)


def test_following_an_instance_reads_its_listing_into_the_sink_on_daemon_threads(
    log: EventLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = BoardFeed()
    started: list[threading.Thread] = []
    real_start = threading.Thread.start
    monkeypatch.setattr(threading.Thread, "start", lambda self: (started.append(self), real_start(self))[1])
    with dagu({"d1": ["a"]}) as (base_url, _):
        follow_instance(base_url, feed.runs("ci"), log, interval=0.01)
        _wait_until(lambda: feed.snapshot()["dags"])

    assert [(t.name, t.daemon) for t in started if t.name.startswith("dagu-")] == [
        ("dagu-runs", True),
        ("dagu-runs-reconcile", True),
    ]
    assert [d["name"] for d in feed.snapshot()["dags"]] == ["ci/d1"]


def test_a_run_appended_to_the_log_moves_its_dag_and_the_end_reads_the_steps_again(
    log: EventLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("starpulse.dagu._reconcile_forever", lambda runs: None)  # only the entries move the DAG
    feed = BoardFeed()
    with dagu({"d1": ["a"]}) as (base_url, calls):
        follow_instance(base_url, feed.runs("ci"), log, interval=0.01)
        _wait_until(lambda: feed.snapshot()["dags"])

        _run_event(log, "start", "running")
        _wait_until(lambda: dag(feed, "d1")["status"] == "running")
        _run_event(log, "end", "failed")
        _wait_until(lambda: dag(feed, "d1")["status"] == "failed")

    assert calls.count(LISTING) == 2  # the first listing, then the ended run's step read


def test_the_runs_the_log_retains_are_replayed_after_the_first_listing_and_older_ones_are_in_that_listing(
    log: EventLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("starpulse.dagu._reconcile_forever", lambda runs: None)
    _run_event(log, "start", "running", workflow="d1", at=1.0)  # long before the listing: Dagu's listing holds it
    _run_event(log, "start", "running", workflow="d2")  # after it
    feed = BoardFeed()
    with dagu({"d1": ["a"], "d2": ["b"]}) as (base_url, _):
        follow_instance(base_url, feed.runs("ci"), log, interval=0.01)
        _wait_until(lambda: feed.snapshot()["dags"] and dag(feed, "d2")["status"] == "running")

    assert dag(feed, "d1")["status"] != "running"


def test_a_followed_instance_reads_only_the_named_dag_when_an_entry_names_a_new_one(
    log: EventLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("starpulse.dagu._reconcile_forever", lambda runs: None)  # its listings would skew the count
    steps = {"d1": ["a"], "d2": ["b"]}
    feed = BoardFeed()
    with dagu(steps) as (base_url, calls):
        follow_instance(base_url, feed.runs("ci"), log, interval=0.01)
        _wait_until(lambda: feed.snapshot()["dags"])
        calls.clear()
        steps["d3"] = ["c"]

        _run_event(log, "start", "running", workflow="d3")
        _wait_until(lambda: any(d["name"] == "ci/d3" for d in feed.snapshot()["dags"]))

    assert calls == [LISTING, "/api/v1/dags/d3"]
    assert dag(feed, "d3")["status"] == "running"


def test_the_starter_asks_dagu_to_start_the_dag_and_returns_the_run_id() -> None:
    sent: list[tuple[str, str, dict | None]] = []

    def transport(method: str, path: str, body: dict | None) -> tuple[int, dict]:
        sent.append((method, path, body))
        return 200, {"dagRunId": "run-1"}

    assert starter(transport)("healthcheck") == "run-1"
    assert sent == [("POST", "/dags/healthcheck/start", {})]


@pytest.mark.parametrize(
    ("transport", "error"),
    [
        (lambda *_: (409, {}), "Dagu refused the start (HTTP 409)"),
        (lambda *_: (200, {}), "Dagu refused the start (HTTP 200)"),
    ],
)
def test_a_start_dagu_refuses_raises_with_its_reason(transport: Transport, error: str) -> None:
    with pytest.raises(StartFailedError, match=re.escape(error)):
        starter(transport)("healthcheck")


def test_a_new_run_clears_the_raw_status_the_last_one_left_on_the_dag_and_its_steps() -> None:
    listed = [
        {
            "name": "d1",
            "status": "failed",
            "raw": "partially_succeeded",
            "runId": "r0",
            "startedAt": "",
            "finishedAt": "",
            "steps": [{"name": "a", "depends": [], "status": "failed", "raw": "rejected", "kind": None}],
        }
    ]
    feed = BoardFeed()
    runs = DaguRuns(feed.runs("ci"), lambda only=None: listed, clock=lambda: LISTED_AT)
    runs.reconcile()

    runs.handle_entry(*run_entry("start", "d1", "r1", "running", at=101.0))

    started = dag(feed, "d1")
    assert "raw" not in started
    assert [("raw" in step, step["status"]) for step in started["steps"]] == [(False, "not_started")]


def test_a_start_that_cannot_reach_dagu_raises_with_the_transports_reason() -> None:
    def transport(method: str, path: str, body: dict | None) -> tuple[int, dict]:
        raise StartFailedError("Dagu unreachable: refused")

    with pytest.raises(StartFailedError) as failed:
        starter(transport)("healthcheck")

    assert str(failed.value) == "Dagu unreachable: refused"


def test_a_run_that_finishes_on_dagu_shows_within_one_reconcile_interval_with_no_log_entries(
    log: EventLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("starpulse.dagu.RECONCILE_INTERVAL", 0.05)
    feed = BoardFeed()
    latest = {"statusLabel": "running", "dagRunId": "r1"}

    def status() -> str:
        return dag(feed, "d1")["status"]

    with dagu({"d1": ["a"]}, latest=latest) as (base_url, _):
        follow_instance(base_url, feed.runs("ci"), log, interval=0.01)
        _wait_until(lambda: feed.snapshot()["dags"] and status() == "running")
        latest["statusLabel"] = "succeeded"
        _wait_until(lambda: status() == "succeeded")


def test_a_streamed_state_outlives_an_older_listing_and_a_newer_listing_replaces_it() -> None:
    now = [100.0]
    latest = {"statusLabel": "queued", "dagRunId": "r1"}
    feed = BoardFeed()
    with dagu({"d1": ["a"]}, latest=latest) as (base_url, _):
        runs = DaguRuns(feed.runs("ci"), lambda only=None: dags(base_url, only), clock=lambda: now[0])
        runs.reconcile()
        assert dag(feed, "d1")["status"] == "queued"

        def listing_overtaken_by_an_entry(only=None) -> list[dict]:
            read = dags(base_url, only)  # Dagu still said queued when this listing read it
            runs.handle_entry(*run_entry("start", "d1", "r1", "running", at=111.0))
            return read

        runs._fetch = listing_overtaken_by_an_entry
        now[0] = 110.0
        runs.reconcile()
        assert dag(feed, "d1")["status"] == "running"

        runs._fetch = lambda only=None: dags(base_url, only)
        latest["statusLabel"] = "succeeded"
        now[0] = 120.0
        runs.reconcile()
        assert dag(feed, "d1")["status"] == "succeeded"


def test_a_listing_that_began_earlier_than_one_already_merged_changes_nothing() -> None:
    now = [100.0]
    latest = {"statusLabel": "queued", "dagRunId": "r1"}
    feed = BoardFeed()
    with dagu({"d1": ["a"]}, latest=latest) as (base_url, _):
        runs = DaguRuns(feed.runs("ci"), lambda only=None: dags(base_url, only), clock=lambda: now[0])

        def listing_overtaken_by_a_newer_one(only=None) -> list[dict]:
            read = dags(base_url, only)  # still queued
            latest["statusLabel"] = "succeeded"
            runs._fetch = lambda only=None: dags(base_url, only)
            now[0] = 110.0
            runs.reconcile()
            return read

        runs._fetch = listing_overtaken_by_a_newer_one
        runs.reconcile()

    assert dag(feed, "d1")["status"] == "succeeded"


def test_an_entry_stamped_at_the_moment_a_listing_began_outlives_that_listing() -> None:
    feed = BoardFeed()
    with dagu({"d1": ["a"]}, latest={"statusLabel": "queued", "dagRunId": "r1"}) as (base_url, _):
        runs = DaguRuns(feed.runs("ci"), lambda only=None: dags(base_url, only), clock=lambda: 100.0)
        runs.reconcile()

        def listing_overtaken_by_an_entry(only=None) -> list[dict]:
            read = dags(base_url, only)
            runs.handle_entry(*run_entry("start", "d1", "r1", "running", at=100.0))
            return read

        runs._fetch = listing_overtaken_by_an_entry
        runs.reconcile()

    assert dag(feed, "d1")["status"] == "running"


def test_a_listing_that_began_at_the_same_moment_as_the_last_is_still_merged() -> None:
    latest = {"statusLabel": "queued", "dagRunId": "r1"}
    feed = BoardFeed()
    with dagu({"d1": ["a"]}, latest=latest) as (base_url, _):
        runs = DaguRuns(feed.runs("ci"), lambda only=None: dags(base_url, only), clock=lambda: 100.0)
        runs.reconcile()

        latest["statusLabel"] = "succeeded"
        runs.reconcile()

    assert dag(feed, "d1")["status"] == "succeeded"


class _Raw:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw
        self.status = 200

    def __enter__(self) -> _Raw:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def test_a_dagu_answer_that_is_not_json_raises_start_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: _Raw(b"<html>bad gateway</html>"))

    with pytest.raises(StartFailedError, match="Dagu returned malformed JSON"):
        connect("http://ci.test")("POST", "/dags/healthcheck/start", {})


@pytest.mark.parametrize("raw", [b"[1, 2]", b'"ok"', b"null", b"3"])
def test_a_dagu_answer_that_is_not_an_object_reads_as_an_empty_body(
    raw: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: _Raw(raw))

    assert connect("http://ci.test")("POST", "/dags/healthcheck/start", {}) == (200, {})


def test_two_concurrent_runs_of_one_dag_are_two_active_records_with_their_own_steps() -> None:
    listed = deliver(in_flight=(WAITING, LINTING))

    assert listed.get("active") == [
        {
            "runId": "r1",
            "status": "running",
            "startedAt": "2026-10-05T23:00:00Z",
            "step": "lint",
            "stepStartedAt": "2026-10-05T23:00:02Z",
            "steps": {"refuse": "succeeded", "lint": "running", "wait_ci": "not_started"},
        },
        {
            "runId": "r2",
            "status": "running",
            "startedAt": "2026-10-05T23:04:00Z",
            "step": "wait_ci",
            "stepStartedAt": "2026-10-05T23:04:30Z",
            "steps": {"refuse": "succeeded", "lint": "succeeded", "wait_ci": "running"},
        },
    ]


def test_a_queued_run_follows_the_running_ones_and_starts_when_it_was_queued() -> None:
    listed = deliver(in_flight=(QUEUED, LINTING))

    assert [
        (a["runId"], a["status"], a["startedAt"], a["step"], a["stepStartedAt"]) for a in listed.get("active", [])
    ] == [
        ("r1", "running", "2026-10-05T23:00:00Z", "lint", "2026-10-05T23:00:02Z"),
        ("r3", "queued", "2026-10-05T23:05:00Z", "", ""),
    ]


def test_a_run_between_steps_has_no_current_step() -> None:
    between = InFlight(
        "deliver",
        "r4",
        started_at="2026-10-05T23:06:00Z",
        nodes=(
            ("refuse", "succeeded", "2026-10-05T23:06:01Z"),
            ("lint", "not_started", ""),
            ("wait_ci", "not_started", ""),
        ),
    )

    assert [(a["step"], a["stepStartedAt"]) for a in deliver(in_flight=(between,)).get("active", [])] == [("", "")]


def test_a_run_of_another_dag_is_not_active_on_this_one() -> None:
    other = InFlight(
        "other", "r9", started_at="2026-10-05T23:00:00Z", nodes=(("a", "running", "2026-10-05T23:00:01Z"),)
    )
    with dagu({**DELIVER, "other": ["a"]}, **LANE, in_flight=(LINTING, other)) as (base_url, _):
        listed = {d["name"]: d for d in dags(base_url)}

    assert [a["runId"] for a in listed["deliver"].get("active", [])] == ["r1"]
    assert [a["runId"] for a in listed["other"].get("active", [])] == ["r9"]


def test_a_dag_names_the_queue_it_declares_as_its_pool() -> None:
    with dagu({**DELIVER, "d2": ["a"]}, queue_of={"deliver": "deliver"}) as (base_url, _):
        listed = {d["name"]: d for d in dags(base_url)}

    assert (listed["deliver"].get("pool"), listed["d2"].get("pool")) == ("deliver", "")


def test_the_pools_are_the_queues_dagu_reports() -> None:
    queues = {"deliver": Queue(cap=32, running=2, queued=1), "default": Queue(cap=2)}
    with dagu(DELIVER, queues=queues) as (base_url, _):
        assert pools(base_url) == [
            {"name": "deliver", "cap": 32, "running": 2, "queued": 1},
            {"name": "default", "cap": 2, "running": 0, "queued": 0},
        ]


def test_a_dagu_that_reports_no_queues_has_no_pools() -> None:
    with dagu(DELIVER) as (base_url, _):
        assert pools(base_url) == []


def test_two_concurrent_runs_and_the_pool_they_share_reach_the_page_under_the_instance() -> None:
    queues = {"deliver": Queue(cap=32, running=2, queued=1)}
    with dagu(DELIVER, **LANE, queues=queues, in_flight=(LINTING, WAITING, QUEUED)) as (base_url, _):
        feed, _, _ = follow(base_url)

    listed = dag(feed, "deliver")
    assert [(a["runId"], a["step"]) for a in listed["active"]] == [("r1", "lint"), ("r2", "wait_ci"), ("r3", "")]
    assert listed["pool"] == "ci/deliver"
    assert feed.snapshot()["pools"] == [{"name": "ci/deliver", "cap": 32, "running": 2, "queued": 1}]


def test_the_pools_travel_with_the_dags_delta_and_a_run_entry_keeps_them() -> None:
    queues = {"deliver": Queue(cap=32, running=2)}
    with dagu(DELIVER, **LANE, queues=queues) as (base_url, _):
        feed, runs, changes = follow(base_url)

        runs.handle_entry(*run_entry("start", "deliver", "r9", "running", at=101.0))

    kind, delta = changes.get_nowait()
    assert (kind, delta["pools"]) == ("dags", [{"name": "ci/deliver", "cap": 32, "running": 2, "queued": 0}])
    assert feed.snapshot()["pools"] == [{"name": "ci/deliver", "cap": 32, "running": 2, "queued": 0}]


def test_a_dagu_that_goes_unreachable_keeps_the_pools_it_last_reported() -> None:
    with dagu(DELIVER, **LANE, queues={"deliver": Queue(cap=32)}) as (base_url, _):
        feed, runs, _ = follow(base_url)

    runs.reconcile()

    assert feed.snapshot()["error"] is not None
    assert [p["name"] for p in feed.snapshot()["pools"]] == ["ci/deliver"]


def test_a_listing_that_reports_no_pools_clears_those_the_last_one_reported() -> None:
    feed = BoardFeed()
    reported = [{"name": "deliver", "cap": 32, "running": 1, "queued": 0}]
    runs = DaguRuns(feed.runs("ci"), lambda only=None: [], lambda: reported, clock=lambda: LISTED_AT)

    runs.reconcile()
    assert [p["name"] for p in feed.snapshot()["pools"]] == ["ci/deliver"]
    reported.clear()
    runs.reconcile()

    assert feed.snapshot()["pools"] == []


def active_ids(feed: BoardFeed) -> list[str]:
    return [a["runId"] for a in dag(feed, "deliver")["active"]]


def test_a_start_entry_adds_its_run_to_the_active_ones_with_every_step_not_started() -> None:
    with dagu(DELIVER, **LANE, in_flight=(LINTING,)) as (base_url, _):
        feed, runs, _ = follow(base_url)

        runs.handle_entry(*run_entry("start", "deliver", "r9", "running", at=101.0))

    started = dag(feed, "deliver")["active"][-1]
    assert active_ids(feed) == ["r1", "r9"]
    assert started == {
        "runId": "r9",
        "status": "running",
        "startedAt": "1970-01-01T00:01:41Z",
        "step": "",
        "stepStartedAt": "",
        "steps": {"refuse": "not_started", "lint": "not_started", "wait_ci": "not_started"},
    }


def test_an_end_entry_drops_its_run_from_the_active_ones_and_keeps_the_others() -> None:
    latest = {"statusLabel": "running", "dagRunId": "r2"}
    with dagu(DELIVER, **LANE, latest=latest, in_flight=(LINTING, WAITING)) as (base_url, _):
        feed, runs, _ = follow(base_url)

        runs.handle_entry(*run_entry("end", "deliver", "r2", "succeeded", at=105.0))

    assert (dag(feed, "deliver")["status"], active_ids(feed)) == ("succeeded", ["r1"])


def test_the_end_of_a_run_that_is_no_longer_the_one_drawn_still_leaves_the_active_ones() -> None:
    latest = {"statusLabel": "running", "dagRunId": "r2"}
    with dagu(DELIVER, **LANE, latest=latest, in_flight=(LINTING, WAITING)) as (base_url, _):
        feed, runs, changes = follow(base_url)

        runs.handle_entry(*run_entry("end", "deliver", "r1", "succeeded", at=105.0))

    assert (dag(feed, "deliver")["runId"], dag(feed, "deliver")["status"], active_ids(feed)) == (
        "r2",
        "running",
        ["r2"],
    )
    assert changes.get_nowait()[0] == "dags"


def test_a_dagu_that_reports_no_pools_and_runs_nothing_yields_empty_pools_and_active() -> None:
    with dagu(DELIVER) as (base_url, _):
        feed, _, _ = follow(base_url)

    assert (dag(feed, "deliver")["active"], dag(feed, "deliver")["pool"], feed.snapshot()["pools"]) == ([], "", [])
