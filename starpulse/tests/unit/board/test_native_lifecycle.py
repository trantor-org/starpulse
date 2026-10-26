"""The lifecycle verbs of a native board: `POST /api/claim`, `POST /api/park` and `POST /api/review` over its writers."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from starpulse.board import criteria
from starpulse.board.adapters.native import board
from starpulse.board.adapters.upstream_backlog import UpstreamBacklog
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import EventLog
from starpulse.tests.unit.board.test_native import native_root, write_task
from starpulse.views.writes import claim_task, park_task, review_task

LAN = "127.0.0.1"
PULL = "https://github.com/acme/app/pull/5"
LANES = ["Ready", "In Progress", "Waiting", "Needs attention", "Review", "Done"]
MACHINE = """\
name: board
states:
  new: {initial: true}
  ready: {role: waiting_on_fact, waits: {criteria_unmet: CRITERIA_UNMET}}
  in_progress: {role: resting}
  waiting: {role: waiting_on_fact, waits: {criteria_met: CRITERIA_MET}}
  needs_attention: {role: waiting_on_person}
  review: {role: waiting_on_fact, waits: {pr_terminal: FINISH}}
  done: {final: true}
events:
  TRIAGE: [{from: new, to: ready}]
  CLAIM: [{from: ready, to: in_progress}]
  PARK: [{from: in_progress, to: waiting}, {from: in_progress, to: needs_attention}]
  REVIEW: [{from: in_progress, to: review}]
  RESUME: [{from: waiting, to: in_progress}, {from: needs_attention, to: in_progress}]
  FINISH: [{from: review, to: done}]
  CRITERIA_UNMET: [{from: ready, to: waiting}]
  CRITERIA_MET: [{from: waiting, to: ready}]
"""
REVIEW_NEEDS_PR: dict[str, Any] = {
    "on": {"to": "Review"},
    "require": {"field": {"field": "references", "matches": r"/pull/\d+$", "min": 1}},
    "reason": "Review needs a pull request in references",
    "skill": "completing-tasks",
}


def _lifecycle(
    base: Path, monkeypatch: pytest.MonkeyPatch, tasks: dict[str, tuple[str, dict[str, object]]], rules: list = ()
) -> tuple[BoardFeed, Board]:
    """A native board with the lifecycle lanes and `rules`, holding `tasks` as (status, fields) by id."""
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval, scanned: (self.scan(), scanned()))
    (base / "board.yaml").write_text(MACHINE)
    native_root(base).mkdir(parents=True)
    (native_root(base) / "config.yml").write_text(
        yaml.safe_dump({"project_name": "demo", "statuses": LANES, "task_prefix": "task"})
    )
    for task, (status, fields) in tasks.items():
        write_task(base, task, status, **fields)
    built = board({"machine": "board.yaml", "guards": list(rules)}, base)
    feed = BoardFeed(machines=built.machines(lambda name: name, ()), keys=built.keys, roles=built.roles)
    built.start(feed, "test", EventLog(f"sqlite:///{base / 'events.sqlite'}"))
    return feed, built


def _scan(base: Path, feed: BoardFeed) -> None:
    """Place what the last write changed: the board's poll does it in a running server."""
    UpstreamBacklog(native_root(base), feed.put).scan()


def _text(base: Path, task: str) -> str:
    return next((native_root(base) / "tasks").glob(f"{task} - *.md")).read_text()


def _claim(feed: BoardFeed, built: Board, **body: object) -> tuple[int, dict[str, Any]]:
    assert built.writer is not None
    return claim_task(LAN, json.dumps(body).encode(), feed, built.writer)


def _park(feed: BoardFeed, built: Board, **body: object) -> tuple[int, dict[str, Any]]:
    return park_task(LAN, json.dumps(body).encode(), feed, built.read, built.edit)


def _review(feed: BoardFeed, built: Board, **body: object) -> tuple[int, dict[str, Any]]:
    return review_task(LAN, json.dumps(body).encode(), feed, built.read, built.edit)


def test_a_claim_moves_the_task_in_progress_and_records_the_session_as_its_assignee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _lifecycle(tmp_path, monkeypatch, {"task-1": ("Ready", {})})

    assert _claim(feed, built, task="task-1", session="s-1") == (
        200,
        {"task": "task-1", "to": "in_progress", "assignee": "s-1"},
    )

    _scan(tmp_path, feed)
    assert [(agent["state"], agent["assignee"]) for agent in feed.open_tasks()] == [("in_progress", "s-1")]


def test_a_claim_names_a_session_and_a_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feed, built = _lifecycle(tmp_path, monkeypatch, {"task-1": ("Ready", {})})

    for body in ({"task": "task-1"}, {"session": "s-1"}, {"task": "task-1", "session": " "}):
        assert _claim(feed, built, **body)[0] == 400
    assert _claim(feed, built, task="task-9", session="s-1")[0] == 404
    assert "status: Ready\n" in _text(tmp_path, "task-1")


def test_a_claim_of_a_task_another_session_holds_is_refused_naming_the_holder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _lifecycle(tmp_path, monkeypatch, {"task-1": ("Ready", {})})
    assert _claim(feed, built, task="task-1", session="s-1")[0] == 200
    _scan(tmp_path, feed)

    status, body = _claim(feed, built, task="task-1", session="s-2")

    assert status == 409 and "s-1" in body["error"] and "already In Progress" in body["error"]
    assert "**Assignee:** s-1" in _text(tmp_path, "task-1")


def test_a_session_that_claims_the_task_it_holds_again_is_told_so_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _lifecycle(tmp_path, monkeypatch, {"task-1": ("Ready", {})})
    assert _claim(feed, built, task="task-1", session="s-1")[0] == 200
    _scan(tmp_path, feed)
    before = _text(tmp_path, "task-1")

    assert _claim(feed, built, task="task-1", session="s-1") == (
        200,
        {"task": "task-1", "to": "in_progress", "assignee": "s-1"},
    )
    assert _text(tmp_path, "task-1") == before


def test_a_session_holding_a_task_in_progress_may_not_claim_a_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _lifecycle(tmp_path, monkeypatch, {"task-1": ("Ready", {}), "task-2": ("Ready", {})})
    assert _claim(feed, built, task="task-1", session="s-1")[0] == 200
    _scan(tmp_path, feed)

    status, body = _claim(feed, built, task="task-2", session="s-1")

    assert status == 409 and "task-1" in body["error"]
    assert "status: Ready\n" in _text(tmp_path, "task-2")
    assert _claim(feed, built, task="task-2", session="s-2")[0] == 200


def test_a_claim_of_a_task_the_machine_does_not_let_an_agent_leave_for_in_progress_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _lifecycle(tmp_path, monkeypatch, {"task-1": ("Done", {})})

    status, body = _claim(feed, built, task="task-1", session="s-1")

    assert status == 409 and "cannot move" in body["error"]


def _in_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rules: list = (), **fields: object) -> tuple:
    feed, built = _lifecycle(tmp_path, monkeypatch, {"task-1": ("In Progress", fields), "task-2": ("Ready", {})}, rules)
    return feed, built


def test_parking_on_a_task_waits_in_waiting_with_the_dependency_added(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch)

    assert _park(feed, built, task="task-1", untilTask=["task-2"], comment="needs 2") == (
        200,
        {"task": "task-1", "to": "waiting"},
    )

    text = _text(tmp_path, "task-1")
    assert "status: Waiting\n" in text and "- task-2" in text and "needs 2" in text


def test_parking_on_a_task_keeps_the_dependencies_it_has(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feed, built = _lifecycle(
        tmp_path,
        monkeypatch,
        {"task-1": ("In Progress", {"dependencies": "[task-3]"}), "task-2": ("Ready", {}), "task-3": ("Ready", {})},
    )

    assert _park(feed, built, task="task-1", untilTask=["task-2", "task-3"])[0] == 200

    assert (built.read("task-1") or {})["dependencies"] == ["task-3", "task-2"]


@pytest.mark.parametrize(
    ("until", "why"),
    [
        (["task-1"], "itself"),
        (["task-9"], "not on the board"),
        (["task-3"], "already Done"),
        ([], "needs"),
        ([" "], "needs"),
        ("task-2", "untilTask: Input should be a valid array"),
    ],
)
def test_parking_on_a_task_that_cannot_be_waited_for_is_refused_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, until: Any, why: str
) -> None:
    feed, built = _lifecycle(
        tmp_path,
        monkeypatch,
        {"task-1": ("In Progress", {}), "task-2": ("Ready", {}), "task-3": ("Done", {})},
    )
    before = _text(tmp_path, "task-1")

    status, body = _park(feed, built, task="task-1", untilTask=until)

    assert status in (400, 404, 409) and why in body["error"]
    assert _text(tmp_path, "task-1") == before


def test_parking_until_a_criterion_writes_the_start_criteria_block_the_board_reads_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch)
    soak = {"id": "soak", "kind": "prom", "expr": "up", "at_least": 1}

    assert _park(feed, built, task="task-1", until=[soak]) == (200, {"task": "task-1", "to": "waiting"})

    record = built.read("task-1") or {}
    assert "status: Waiting\n" in _text(tmp_path, "task-1")
    assert [(item["id"], item["kind"], item["expr"]) for item in criteria.authored(record["description"])] == [
        ("soak", "prom", "up")
    ]
    assert record["description"].startswith("Why")


def test_parking_until_a_criterion_replaces_the_criteria_it_had(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch)
    first, second = ({"id": name, "kind": "prom", "expr": "up"} for name in ("first", "second"))

    assert _park(feed, built, task="task-1", until=[first])[0] == 200
    assert (built.read("task-1") or {})["description"].count("## Start Criteria") == 1
    # back in progress by the operator's hand: the second park finds the first block and replaces it
    path = next((native_root(tmp_path) / "tasks").glob("task-1 - *.md"))
    path.write_text(path.read_text().replace("status: Waiting", "status: In Progress"))
    _scan(tmp_path, feed)
    assert _park(feed, built, task="task-1", until=[second])[0] == 200

    record = built.read("task-1") or {}
    assert record["description"].count("## Start Criteria") == 1
    assert [item["id"] for item in criteria.authored(record["description"])] == ["second"]


@pytest.mark.parametrize(
    "until",
    [[], [{"kind": "prom"}], [{"id": "a"}], [{"id": "a", "kind": "prom"}, {"id": "a", "kind": "prom"}]],
)
def test_parking_until_malformed_criteria_is_refused_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, until: list
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch)
    before = _text(tmp_path, "task-1")

    status, body = _park(feed, built, task="task-1", until=until)

    assert status == 400 and "criteri" in body["error"]
    assert _text(tmp_path, "task-1") == before


def test_parking_until_a_criterion_that_is_not_an_object_is_a_400_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch)
    before = _text(tmp_path, "task-1")

    status, body = _park(feed, built, task="task-1", until=["soak"])

    assert (status, body) == (400, {"error": "invalid request: until.0: Input should be an object"})
    assert _text(tmp_path, "task-1") == before


def test_a_task_gated_by_an_open_dependency_is_not_also_parked_on_a_criterion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch, dependencies="[task-2]")
    before = _text(tmp_path, "task-1")

    status, body = _park(feed, built, task="task-1", until=[{"id": "a", "kind": "prom"}])

    assert status == 409 and "task-2" in body["error"] and "one reason" in body["error"]
    assert _text(tmp_path, "task-1") == before


def test_parking_on_the_operator_waits_in_needs_attention_with_the_reason_in_its_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch)

    assert _park(feed, built, task="task-1", operator="pick a host") == (
        200,
        {"task": "task-1", "to": "needs_attention"},
    )

    record = built.read("task-1") or {}
    assert "status: Needs attention\n" in _text(tmp_path, "task-1")
    assert record["description"].endswith("## Needs attention\n\npick a host")


def test_a_second_operator_park_replaces_the_reason_rather_than_stacking_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch)
    assert _park(feed, built, task="task-1", operator="first")[0] == 200
    path = next((native_root(tmp_path) / "tasks").glob("task-1 - *.md"))
    path.write_text(path.read_text().replace("status: Needs attention", "status: In Progress"))
    _scan(tmp_path, feed)

    assert _park(feed, built, task="task-1", operator="second")[0] == 200

    description = (built.read("task-1") or {})["description"]
    assert description.count("## Needs attention") == 1 and "second" in description and "first" not in description


def test_a_park_whose_reason_is_not_text_is_a_400_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch)
    before = _text(tmp_path, "task-1")

    status, body = _park(feed, built, task="task-1", operator=3)

    assert (status, body) == (400, {"error": "invalid request: operator: Input should be a valid string"})
    assert _text(tmp_path, "task-1") == before


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"operator": " "},
        {"operator": "x", "untilTask": ["task-2"]},
        {"untilTask": ["task-2"], "until": [{"id": "a", "kind": "prom"}]},
    ],
)
def test_a_park_names_exactly_one_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: dict) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch)
    before = _text(tmp_path, "task-1")

    status, answer = _park(feed, built, task="task-1", **body)

    assert status == 400 and "reason" in answer["error"]
    assert _text(tmp_path, "task-1") == before


def test_only_a_task_in_progress_may_be_parked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch)

    status, body = _park(feed, built, task="task-2", operator="why")

    assert status == 409 and "In Progress" in body["error"]


def test_a_park_a_rule_refuses_returns_the_rules_reason_and_skill_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waiting_needs_a_dependency = {
        "on": {"to": "Waiting"},
        "require": {"field": {"field": "dependencies", "min": 1}},
        "reason": "Waiting needs a dependency",
        "skill": "starting-tasks",
    }
    feed, built = _in_progress(tmp_path, monkeypatch, [waiting_needs_a_dependency])
    before = _text(tmp_path, "task-1")

    status, body = _park(feed, built, task="task-1", until=[{"id": "a", "kind": "prom"}])

    assert (status, body) == (409, {"error": "Waiting needs a dependency", "skill": "starting-tasks"})
    assert _text(tmp_path, "task-1") == before


def test_a_review_moves_the_task_with_its_pull_request_and_summary_as_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch, [REVIEW_NEEDS_PR])

    assert _review(feed, built, task="task-1", references=[PULL], summary="Shipped it.", comment="PR up") == (
        200,
        {"task": "task-1", "to": "review"},
    )

    record = built.read("task-1") or {}
    assert "status: Review\n" in _text(tmp_path, "task-1")
    assert (record["references"], record["finalSummary"]) == ([PULL], "Shipped it.")


def test_a_review_keeps_the_references_the_task_has_and_adds_each_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch, references="[https://example.com/design]")

    assert _review(feed, built, task="task-1", references=[PULL, PULL, "https://example.com/design"])[0] == 200

    assert (built.read("task-1") or {})["references"] == ["https://example.com/design", PULL]


def test_a_review_the_rules_judge_unready_is_refused_with_their_reason_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch, [REVIEW_NEEDS_PR])
    before = _text(tmp_path, "task-1")

    status, body = _review(feed, built, task="task-1", summary="Shipped it.")

    assert (status, body) == (409, {"error": "Review needs a pull request in references", "skill": "completing-tasks"})
    assert _text(tmp_path, "task-1") == before


def test_a_review_refuses_a_task_the_machine_does_not_let_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch)

    status, body = _review(feed, built, task="task-2")

    assert status == 409 and "cannot move" in body["error"]


@pytest.mark.parametrize("body", [{"references": "x"}, {"references": [3]}, {"summary": 3}, {"task": 3}])
def test_a_review_with_evidence_of_the_wrong_shape_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: dict
) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch)

    status, _ = _review(feed, built, **{"task": "task-1", **body})

    assert status == 400
    assert "status: In Progress\n" in _text(tmp_path, "task-1")


def test_the_lifecycle_verbs_answer_only_the_lan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feed, built = _in_progress(tmp_path, monkeypatch)
    raw = json.dumps({"task": "task-1", "session": "s", "operator": "x"}).encode()

    assert claim_task("8.8.8.8", raw, feed, built.writer)[0] == 403
    assert park_task("8.8.8.8", raw, feed, built.read, built.edit)[0] == 403
    assert review_task("8.8.8.8", raw, feed, built.read, built.edit)[0] == 403
