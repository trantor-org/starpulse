"""The self-contained demo page: live structure, synthetic agents, one file."""

import io
import json
import re
import urllib.request
from pathlib import Path

import jsonschema
import pytest

from starpulse.cli.demo import TITLES, _send_back, capture, elements, mockup, page, scrub, scrub_board, scrub_mockup
from starpulse.contracts.adapters import SCHEMAS, Dag, Pool
from starpulse.projections.ci import CI_MACHINES

SECRET = "Rotate the router admin password"


def _live() -> dict:
    task = {
        "id": "PROJ-2201",
        "title": SECRET,
        "description": SECRET,
        "state": "in_progress",
        "model": "claude-opus",
        "labels": ["kind-execute"],
        "dependencies": ["PROJ-2190"],
        "prs": ["https://github.com/o/r/pull/7"],
    }
    placed = {
        "id": "PROJ-2201",
        "title": "PROJ-2201",
        "task": "PROJ-2201",
        "state": "docs_reconciled",
        "model": "",
        "steps": 3,
        "trail": [{"state": "docs_reconciled", "event": "DOCS_RECONCILED", "at": 1.0}],
        "active": 1.0,
    }
    return {
        "graphs": ["board", "in-progress", "runs"],
        "boardUrl": "http://board.lan/tasks",
        "domains": [{"name": "ops", "dags": [{"name": "nightly", "runSafe": True}]}],
        "dags": [
            {"name": "nightly", "status": "running", "runId": "r-77", "startedAt": "", "finishedAt": "", "steps": []}
        ],
        "flows": [
            {"name": "board", "machine": {"states": []}, "agents": [task]},
            {"name": "in-progress", "machine": {"states": []}, "agents": [placed]},
        ],
        "settled": {"PROJ-2100": {"state": "completed", "at": None, "created": None, "title": SECRET, "model": ""}},
        "error": "ci: down",
        "now": 1.0,
    }


def _with_deliver(live: dict) -> dict:
    live["domains"] = [{"name": "Delivery", "dags": [{"name": "dagu/deliver", "runSafe": False}]}]
    live["dags"] = []
    return live


def test_scrub_seeds_running_deliver_runs_and_their_pool_when_the_capture_has_no_pools() -> None:
    demo = scrub(_with_deliver(_live()))

    deliver = next(d for d in demo["dags"] if d["name"] == "dagu/deliver")
    steps = {s["name"] for s in deliver["steps"]}
    assert len(deliver["active"]) == 3
    assert {r["status"] for r in deliver["active"]} == {"running"}
    assert {r["step"] for r in deliver["active"]} <= steps
    assert all(set(r["steps"]) <= steps for r in deliver["active"])
    assert len({r["runId"] for r in deliver["active"]}) == 3
    pools = {p["name"]: p for p in demo["pools"]}
    assert deliver["pool"] == "dagu/deliver"
    assert pools["dagu/deliver"] == {"name": "dagu/deliver", "cap": 32, "running": 3, "queued": 0}
    assert pools["dagu/default"]["running"] == 0


def test_scrub_seeds_pools_and_runs_that_follow_the_contract() -> None:
    demo = scrub(_with_deliver(_live()))

    for dag in demo["dags"]:
        jsonschema.validate(Dag.model_validate(dag).model_dump(mode="json", by_alias=True), SCHEMAS["runs"])
    for pool in demo["pools"]:
        jsonschema.validate(Pool.model_validate(pool).model_dump(mode="json", by_alias=True), SCHEMAS["pools"])


def _with_catalog(live: dict) -> dict:
    """One domain: `deliver`, the three DAGs `_finished` gives a finished run, then the four the catalog cycles."""
    names = ("deliver", "f1", "f2", "f3", "apply-on-merge", "whole-repo-gate", "backlog-sweep", "board-autopilot")
    live["domains"] = [{"name": "Delivery", "dags": [{"name": f"dagu/{n}", "runSafe": False} for n in names]}]
    live["dags"] = []
    return live


def test_scrub_seeds_every_other_declared_dag_in_a_state_of_its_own_and_marks_some_run_safe() -> None:
    demo = scrub(_with_catalog(_live()))

    by = {d["name"]: d for d in demo["dags"]}
    assert {n.removeprefix("dagu/"): d["status"] for n, d in by.items()} == {
        "deliver": "running",
        "f1": "succeeded",
        "f2": "succeeded",
        "f3": "succeeded",
        "apply-on-merge": "failed",
        "whole-repo-gate": "succeeded",
        "backlog-sweep": "not_started",
        "board-autopilot": "queued",
    }
    failed = by["dagu/apply-on-merge"]
    assert "failed" in {s["status"] for s in failed["steps"]}
    assert failed["finishedAt"]
    assert by["dagu/backlog-sweep"]["finishedAt"] == ""
    safe = {x["name"]: x["runSafe"] for g in demo["domains"] for x in g["dags"]}
    assert safe["dagu/deliver"] is False
    assert any(safe.values()) and not all(safe.values())
    for dag in demo["dags"]:
        jsonschema.validate(Dag.model_validate(dag).model_dump(mode="json", by_alias=True), SCHEMAS["runs"])


def test_scrub_seeds_no_catalog_when_the_capture_reports_pools() -> None:
    live = _with_catalog(_live())
    live["pools"] = [{"name": "dagu/deliver", "cap": 8, "running": 0, "queued": 0}]

    demo = scrub(live)

    assert demo["dags"] == []
    assert not any(x["runSafe"] for g in demo["domains"] for x in g["dags"])


def test_scrub_keeps_the_pools_a_capture_reports_and_seeds_nothing() -> None:
    live = _with_deliver(_live())
    live["pools"] = [{"name": "dagu/deliver", "cap": 8, "running": 0, "queued": 0}]

    demo = scrub(live)

    assert demo["pools"] == live["pools"]
    assert demo["dags"] == []


def test_scrub_seeds_no_second_deliver_dag_when_the_capture_already_reads_one() -> None:
    live = _with_deliver(_live())
    live["dags"] = [
        {"name": "dagu/deliver", "status": "succeeded", "runId": "r-1", "startedAt": "", "finishedAt": "", "steps": []}
    ]

    demo = scrub(live)

    assert [d["name"] for d in demo["dags"]] == ["dagu/deliver"]
    assert "pools" not in demo


def test_scrub_seeds_no_pools_when_the_capture_has_no_deliver_workflow() -> None:
    demo = scrub(_live())

    assert demo.get("pools", []) == []
    assert [d["name"] for d in demo["dags"]] == ["nightly"]


def test_scrub_keeps_the_structure_and_replaces_every_task() -> None:
    live = _live()
    live["flows"][0]["agents"] += [{"id": f"PROJ-{i}", "title": SECRET, "state": "ready"} for i in range(8)]

    demo = scrub(live)

    text = json.dumps(demo)
    for leak in (
        SECRET,
        "PROJ-2201",
        "PROJ-2190",
        "PROJ-2100",
        "pull/7",
        "board.lan",
        "r-77",
        "ci: down",
    ):
        assert leak not in text
    board, placed = demo["flows"][0]["agents"], demo["flows"][1]["agents"]
    assert board[0] == {
        "id": "DEMO-1",
        "title": TITLES[0],
        "state": "in_progress",
        "model": "claude-opus",
        "milestone": "",
        "labels": ["kind-execute"],
        "dependencies": [],
        "description": f"Synthetic demo task: {TITLES[0].lower()}.",
    }
    assert board[8] == {
        "id": "DEMO-9",
        "title": TITLES[8],
        "state": "ready",
        "model": "",
        "milestone": "",
        "labels": [],
        "dependencies": [],
        "description": f"Synthetic demo task: {TITLES[8].lower()}.",
    }
    # the machine's task keeps the name its Board task was given, so it still sits on the Board
    assert placed == [
        {
            "state": "docs_reconciled",
            "model": "",
            "steps": 3,
            "trail": [{"state": "docs_reconciled", "event": "DOCS_RECONCILED", "at": 1.0}],
            "active": 1.0,
            "id": "DEMO-1",
            "title": TITLES[0],
            "task": "DEMO-1",
        }
    ]
    assert {k: demo[k] for k in ("boardUrl", "domains", "settled", "error", "graphs", "now")} == {
        "boardUrl": None,
        "domains": [{"name": "ops", "dags": [{"name": "nightly", "runSafe": False}]}],
        "settled": {},
        "error": None,
        "graphs": ["board", "in-progress", "runs"],
        "now": 1.0,
    }
    assert [(d["name"], d["runId"], d["status"]) for d in demo["dags"]] == [("nightly", "demo-0", "running")]
    assert [f["machine"] for f in demo["flows"]] == [{"states": []}, {"states": []}]


def test_scrub_renames_each_active_run_of_a_dag_as_it_does_the_latest_run() -> None:
    live = _live()
    active = {"status": "running", "startedAt": "", "step": "", "stepStartedAt": "", "steps": {}}
    live["dags"][0]["active"] = [{**active, "runId": "deliver-agent-task-2836-secret"}, {**active, "runId": "r-2"}]

    demo = scrub(live)

    assert [a["runId"] for a in demo["dags"][0]["active"]] == ["demo-0-0", "demo-0-1"]
    assert "secret" not in json.dumps(demo)


def test_scrub_keeps_a_board_tasks_bucket_labels_and_dependencies_under_demo_names() -> None:
    live = _live()
    live["flows"][0]["agents"] = [
        {
            "id": "PROJ-1",
            "title": SECRET,
            "state": "ready",
            "milestone": "m-76",
            "labels": ["kind-fix", "payroll-audit"],
        },
        {
            "id": "PROJ-2",
            "title": SECRET,
            "state": "waiting",
            "milestone": "m-76",
            "dependencies": ["PROJ-1", "PROJ-9"],
        },
        {"id": "PROJ-3", "title": SECRET, "state": "done", "milestone": "m-100", "description": SECRET},
    ]

    board = scrub(live)["flows"][0]["agents"]

    assert [(a["milestone"], a["labels"], a["dependencies"]) for a in board] == [
        ("m-1", ["kind-fix"], []),
        ("m-1", [], ["DEMO-1"]),
        ("m-2", [], []),
    ]
    assert board[2]["description"] == f"Synthetic demo task: {TITLES[2].lower()}."
    assert not {"m-76", "m-100", "payroll-audit", SECRET} & set(json.dumps(board).split('"'))


def test_scrub_keeps_when_each_board_task_entered_its_lane_so_the_demo_orders_its_columns_as_the_live_board() -> None:
    live = _live()
    live["flows"][0]["agents"] = [
        {"id": "PROJ-1", "title": SECRET, "state": "ready", "entered": 30.0},
        {"id": "PROJ-2", "title": SECRET, "state": "ready"},
    ]

    board = scrub(live)["flows"][0]["agents"]

    assert [a.get("entered") for a in board] == [30.0, None]


def test_scrub_keeps_since_when_each_board_task_has_been_workable_so_the_demo_draws_the_leaderboard() -> None:
    live = _live()
    live["flows"][0]["agents"] = [
        {"id": "PROJ-1", "title": SECRET, "state": "ready", "workable_since": 30.0},
        {"id": "PROJ-2", "title": SECRET, "state": "waiting", "workable_since": None},
        {"id": "PROJ-3", "title": SECRET, "state": "ready"},
    ]

    board = scrub(live)["flows"][0]["agents"]

    assert [a.get("workable_since", "absent") for a in board] == [30.0, None, "absent"]


def test_scrub_names_a_session_of_a_task_off_the_board_after_the_board_tasks() -> None:
    live = _live()
    live["flows"][1]["agents"].append({"id": "PROJ-9999", "state": "committed", "model": ""})

    session = scrub(live)["flows"][1]["agents"][1]

    assert (session["id"], session["task"], session["title"]) == ("DEMO-2", "DEMO-2", TITLES[1])


def test_scrub_replaces_each_pull_request_with_a_synthetic_one_on_the_task_demo_name() -> None:
    live = _live()
    live["pulls"] = {
        "PROJ-2201": [
            {
                "number": 7,
                "url": "https://github.com/o/r/pull/7",
                "checks": "failing",
                "merged": False,
                "threads": 2,
                "stale": True,
            }
        ],
        "PROJ-5000": [
            {
                "number": 9,
                "url": "https://github.com/o/r/pull/9",
                "checks": "pass",
                "merged": True,
                "threads": 0,
                "stale": False,
            }
        ],
    }

    demo = scrub(live)

    assert demo["pulls"] == {
        "DEMO-1": [{"number": 100, "url": "#", "checks": "failing", "merged": False, "threads": 2, "stale": False}]
    }
    assert "github.com" not in json.dumps(demo)


def test_scrub_keeps_each_task_settled_in_the_last_day_under_a_demo_name_and_a_board_tasks_created_time() -> None:
    live = _live()
    now = live["now"] = 100_000.0
    live["flows"][0]["agents"][0]["created"] = now - 600
    live["settled"] = {
        "PROJ-2100": {"state": "archived", "at": now - 3600, "created": now - 7200, "title": SECRET, "model": "opus"},
        "PROJ-2000": {"state": "completed", "at": now - 2 * 86400, "created": None, "title": SECRET, "model": ""},
    }

    demo = scrub(live)

    assert demo["flows"][0]["agents"][0]["created"] == now - 600
    assert demo["settled"] == {
        "DEMO-2": {"state": "archived", "at": now - 3600, "created": now - 7200, "title": TITLES[1], "model": "opus"}
    }


def test_scrub_seeds_the_days_arrivals_with_the_board_it_seeds() -> None:
    live = _live()
    live["flows"][0]["agents"] = []
    now = live["now"] = 100_000.0

    demo = scrub(live)

    settled, created = demo["settled"].values(), [a["created"] for a in demo["flows"][0]["agents"] if "created" in a]
    assert {e["state"] for e in settled} == {"completed", "archived"}
    assert all(now - 7200 < e["at"] <= now and e["title"] in TITLES for e in settled)
    assert created and all(now - 7200 < at <= now for at in created)


def test_the_seeded_board_says_since_when_each_open_task_has_been_workable_so_the_leaderboard_has_rows() -> None:
    live = _live()
    live["flows"][0]["agents"] = []

    board = scrub(live)["flows"][0]["agents"]

    now = live["now"]
    for state in ("needs_attention", "in_progress", "review", "waiting", "ready"):
        since = [a["workable_since"] for a in board if a["state"] == state]
        assert any(s is not None and 0 < now - s < 4 * 86400 for s in since), state
    assert all(a["workable_since"] is None for a in board if a["dependencies"] and a["state"] not in ("done", "waiting"))
    assert any(a["workable_since"] is None for a in board if a["state"] == "waiting")
    assert all("workable_since" not in a for a in board if a["state"] in ("new", "done"))


def test_the_seeded_board_has_a_waiting_chain_for_the_kanban_stack() -> None:
    live = _live()
    live["flows"][0]["agents"] = []

    board = scrub(live)["flows"][0]["agents"]

    waiting = {a["id"]: a for a in board if a["state"] == "waiting" and a["milestone"] == "m-2"}
    assert board[3]["id"] in waiting  # the head: it waits on a Ready task, so no Waiting blocker
    assert [a["dependencies"] for a in board[14:17]] == [["DEMO-4"], ["DEMO-15"], ["DEMO-15"]]
    assert all(a["id"] in waiting for a in board[14:17])


def test_the_seeded_board_has_a_done_chain_for_the_kanban_stack() -> None:
    live = _live()
    live["flows"][0]["agents"] = []

    board = scrub(live)["flows"][0]["agents"]

    chain = board[12], *board[17:19]
    assert [a["dependencies"] for a in board[17:19]] == [["DEMO-13"], ["DEMO-18"]]
    assert all(a["state"] == "done" and a["milestone"] == chain[0]["milestone"] for a in chain)
def test_the_seeded_board_has_a_review_task_with_two_pulls_and_a_task_holding_three_others() -> None:
    live = _live()
    live["flows"][0]["agents"] = []

    demo = scrub(live)

    board = demo["flows"][0]["agents"]
    assert board[20]["state"] == "review" and len(demo["pulls"][board[20]["id"]]) == 2
    assert len({p["number"] for p in demo["pulls"][board[20]["id"]]}) == 2
    held = [a for a in board if board[6]["id"] in a["dependencies"]]
    assert [a["state"] for a in held] == ["waiting"] * 3


def test_scrub_seeds_one_ci_agent_per_task_with_pull_requests_walking_the_machine_per_pull_request() -> None:
    live = _live()
    live["flows"][0]["agents"] = []
    live["flows"].append({"name": "ci", "machine": CI_MACHINES["ci"], "agents": []})

    demo = scrub(live)

    flow = next(f for f in demo["flows"] if f["name"] == "ci")
    ci = {a["task"]: a for a in flow["agents"]}
    assert set(ci) == set(demo["pulls"])  # a task with no pull request is in no ci agent
    two = ci["DEMO-21"]  # a Review task with a merged pull request, then an open one
    assert [s["event"] for s in two["trail"]].count("PR_OPENED") == 2 and two["state"] == "passing"
    assert ci["DEMO-8"]["state"] == "failing" and ci["DEMO-8"]["trail"][-1]["event"] == "CHECKS_FAILED"
    next_state = {(t["source"], t["event"]): t["target"] for t in flow["machine"]["transitions"]}
    for agent in ci.values():
        assert agent["steps"] == len(agent["trail"]) and agent["active"] == agent["trail"][-1]["at"] <= live["now"]
        assert [s["at"] for s in agent["trail"]] == sorted(s["at"] for s in agent["trail"])
        steps = zip(agent["trail"], agent["trail"][1:])
        assert all(next_state[(a["state"], b["event"])] == b["state"] for a, b in steps)


def test_the_seeded_board_has_a_waiting_task_blocked_from_another_milestone_for_the_kanban_link() -> None:
    live = _live()
    live["flows"][0]["agents"] = []

    board = {a["id"]: a for a in scrub(live)["flows"][0]["agents"]}

    linked = [
        a for a in board.values()
        if a["state"] == "waiting" and any(board[d]["state"] == "waiting" and board[d]["milestone"] != a["milestone"] for d in a["dependencies"])
    ]
    assert len(linked) == 1  # the Kanban draws its link badge, and it is not a self-dependency


def test_scrub_seeds_a_board_when_the_capture_has_none() -> None:
    live = _live()
    live["flows"][0]["agents"] = []

    demo = scrub(live)

    board = demo["flows"][0]["agents"]
    assert {a["state"] for a in board} == {"ready", "waiting", "in_progress", "review", "needs_attention", "done"}
    assert len({a["milestone"] for a in board}) >= 3  # two milestones and the tasks with none
    assert board[0] == {
        "id": "DEMO-1",
        "title": TITLES[0],
        "state": "ready",
        "model": "@agent-fast-low",
        "milestone": "m-2",
        "labels": ["size-2", "kind-feature"],
        "dependencies": [],
        "description": f"Synthetic demo task: {TITLES[0].lower()}.",
        "created": live["now"] - 900,
        "workable_since": live["now"] - 900,
    }
    assert board[3]["dependencies"] == ["DEMO-1"] and board[3]["labels"] == ["size-5", "needs-human"]
    assert demo["pulls"]["DEMO-9"] == [
        {"number": 108, "url": "#", "checks": "pass", "merged": False, "threads": 2, "stale": False}
    ]
    assert demo["pulls"]["DEMO-12"][0]["merged"] is True
    assert set(demo["pulls"]) <= {a["id"] for a in board}
    assert not re.search(r"PROJ-\d|github\.com", json.dumps(demo))


def test_scrub_draws_every_kanban_lane_with_a_card_when_the_capture_board_is_the_native_three_lane_machine() -> None:
    live = _live()
    native = [("to_do", True, False), ("in_progress", False, False), ("done", False, True)]
    live["flows"][0] = {
        "name": "board",
        "agents": [],
        "machine": {
            "states": [{"id": i, "name": i, "initial": init, "final": fin} for i, init, fin in native],
            "transitions": [],
            "mainLine": [i for i, _, _ in native],
        },
    }

    demo = scrub(live)

    board = demo["flows"][0]
    lanes = [s["id"] for s in board["machine"]["states"]]
    assert lanes == ["ready", "waiting", "in_progress", "review", "needs_attention", "done"]
    assert {a["state"] for a in board["agents"]} == set(lanes)
    assert board["machine"]["mainLine"] == lanes


def test_scrub_keeps_the_machine_of_a_capture_that_has_its_own_board() -> None:
    live = _live()
    machine = {"states": [{"id": "to_do", "name": "To Do", "initial": True}], "transitions": []}
    live["flows"][0] = {**live["flows"][0], "machine": machine}

    assert scrub(live)["flows"][0]["machine"] == machine


def test_capture_reads_the_snapshot_a_connection_to_the_event_stream_opens_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = b'event: snapshot\ndata: {"flows": [{"name": "board"}]}\n\nevent: task\ndata: {"id": "PROJ-1"}\n\n'
    fetched = []

    def urlopen(url: str, timeout: float) -> io.BytesIO:
        fetched.append((url, timeout))
        return io.BytesIO(stream)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert capture("http://flow") == {"flows": [{"name": "board"}]}
    assert fetched == [("http://flow/api/events", 30)]


def test_capture_refuses_a_stream_that_sends_no_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: io.BytesIO(b": ping\n\n"))

    with pytest.raises(ValueError, match="no snapshot"):
        capture("http://flow")


def test_page_inlines_the_bundle_and_embeds_the_fixture(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-a.js").write_text("x('</script>')")
    (tmp_path / "assets" / "index-b.css").write_text("body{margin:0}")
    (tmp_path / "index.html").write_text(
        '<head>\n  <script type="module" crossorigin src="/assets/index-a.js"></script>\n'
        '  <link rel="stylesheet" crossorigin href="/assets/index-b.css">\n</head>'
    )

    html = page(tmp_path, {"title": "</script>"})

    assert html == (
        '<head>\n  <script>window.__FLOW_FIXTURE__ = {"title": "<\\/script>"}</script>\n'
        "  <script type=\"module\">x('<\\/script>')</script>\n"
        "  <style>body{margin:0}</style>\n</head>"
    )


def _snap() -> dict:
    live = _live()
    board, sessions = live["flows"][0], live["flows"][1]
    board["agents"].append({"id": "PROJ-2202", "title": "Second task", "state": "ready", "labels": ["vm-only"]})
    sessions["agents"] = [
        {
            "id": "b5f1c2d4",
            "title": "session b5f1c2d4",
            "model": "claude-sonnet",
            "kind": "interactive",
            "badges": [],
            "task": "PROJ-2202",
            "active": 1.0,
            "state": "reviewing",
            "steps": 3,
            "trail": [{"state": "reviewing", "event": "review", "at": 1.0}],
        }
    ]
    sessions["agents"][0]["trail"][0]["detail"] = SECRET
    return {
        "now": 1.0,
        "dags": live["dags"],
        "writers": {"CLAIM": [{"actor": "agent", "trigger": "bin/backlog_task.py dispatch"}]},
        "launches": [{"dag": "nightly", "skill": "auditing", "flow": "auditing"}],
        "domains": live["domains"],
        "descriptions": {"PROJ-2201": SECRET, "PROJ-2202": "Fixes PROJ-2190"},
        "flows": {"board": board, "in-progress": sessions},
    }


def test_scrub_mockup_replaces_identities_and_keeps_links() -> None:
    demo = scrub_mockup(_snap())

    text = json.dumps(demo)
    for leak in (SECRET, "PROJ-", "Second task", "b5f1c2d4", "pull/7", "r-77", "vm-only"):
        assert leak not in text
    board, sessions = demo["flows"]["board"]["agents"], demo["flows"]["in-progress"]["agents"]
    assert board[0] == {
        "id": "DEMO-1",
        "title": TITLES[0],
        "state": "in_progress",
        "model": "claude-opus",
        "labels": ["kind-execute"],
        "dependencies": [],
        "prs": [],
    }
    assert [b["id"] for b in board] == ["DEMO-1", "DEMO-2"]
    assert sessions == [
        {
            "id": "00000001-0000-4000-8000-000000000000",
            "title": "demo session 1",
            "model": "claude-sonnet",
            "kind": "interactive",
            "badges": [],
            "task": "DEMO-2",
            "active": 1.0,
            "state": "reviewing",
            "steps": 3,
            "trail": [{"state": "reviewing", "event": "review", "at": 1.0}],
        }
    ]
    assert demo["descriptions"] == {
        "DEMO-1": f"Synthetic demo task: {TITLES[0].lower()}.",
        "DEMO-2": f"Synthetic demo task: {TITLES[1].lower()}.",
    }
    assert [d["runId"] for d in demo["dags"]] == ["demo-0"]
    assert demo["domains"] == [{"name": "ops", "dags": [{"name": "nightly", "runSafe": False}]}]
    assert {k: demo[k] for k in ("now", "writers", "launches")} == {
        k: _snap()[k] for k in ("now", "writers", "launches")
    }


def test_scrub_mockup_drops_a_task_link_to_a_task_off_the_board() -> None:
    snap = _snap()
    snap["flows"]["in-progress"]["agents"][0]["task"] = "PROJ-9999"

    assert scrub_mockup(snap)["flows"]["in-progress"]["agents"][0]["task"] is None


def test_scrub_mockup_fills_what_a_bare_agent_leaves_out() -> None:
    snap = _snap()
    snap["flows"]["board"]["agents"] = [{"id": "PROJ-1", "title": "t", "state": "ready"}]
    snap["flows"]["in-progress"]["agents"] = [{"id": "s", "title": "t", "state": "idle"}]

    demo = scrub_mockup(snap)["flows"]

    assert demo["board"]["agents"][0]["labels"] == []
    session = demo["in-progress"]["agents"][0]
    assert {k: session[k] for k in ("model", "kind", "steps", "trail", "task", "active")} == {
        "model": "",
        "kind": "",
        "steps": 0,
        "trail": [],
        "task": None,
        "active": None,
    }


def test_scrub_mockup_leaves_out_domains_the_mockup_has_none_of() -> None:
    snap = _snap()
    del snap["domains"]

    assert "domains" not in scrub_mockup(snap)


def test_scrub_mockup_refuses_a_key_it_does_not_know() -> None:
    with pytest.raises(ValueError, match="secrets"):
        scrub_mockup({**_snap(), "secrets": []})


def test_mockup_inlines_the_scrubbed_data(tmp_path: Path) -> None:
    (tmp_path / "data.js").write_text("window.SNAP = " + json.dumps(_snap()) + ";\n")
    (tmp_path / "index.html").write_text('<body>\n<script src="data.js"></script>\n</body>')

    html = mockup(tmp_path)

    data = json.dumps(scrub_mockup(_snap())).replace("</", "<\\/")
    assert html == f"<body>\n<script>window.SNAP = {data};</script>\n</body>"


def test_mockup_inlines_its_history_renamed_like_its_board(tmp_path: Path) -> None:
    (tmp_path / "data.js").write_text("window.SNAP = " + json.dumps(_snap()) + ";\n")
    hist = {"PROJ-2202": [[1.0, "new", "ready", {"by": "agent"}]], "PROJ-9999": [[2.0, "ready", "done"]]}
    (tmp_path / "history.js").write_text("// lane changes\nwindow.HIST = " + json.dumps(hist) + ";\n")
    (tmp_path / "index.html").write_text('<script src="data.js"></script><script src="history.js"></script>')

    html = mockup(tmp_path)

    assert 'window.HIST = {"DEMO-2": [[1.0, "new", "ready", {"by": "agent"}]]};' in html
    assert "PROJ-" not in html and 'src="' not in html


def test_mockup_inlines_its_other_scripts(tmp_path: Path) -> None:
    (tmp_path / "data.js").write_text("window.SNAP = " + json.dumps(_snap()) + ";\n")
    (tmp_path / "trace.js").write_text('const card = () => "<div></div><\\/script>"; // </script>\n')
    (tmp_path / "index.html").write_text('<script src="data.js"></script><script src="trace.js"></script>')

    html = mockup(tmp_path)

    assert 'const card = () => "<div></div><\\/script>"; // <\\/script>' in html
    assert 'src="' not in html and html.count("</script>") == 2


def test_mockup_escapes_a_closing_tag_in_the_data(tmp_path: Path) -> None:
    snap = {**_snap(), "writers": {"X": [{"actor": "a", "trigger": "</script>"}]}}
    (tmp_path / "data.js").write_text("window.SNAP = " + json.dumps(snap) + ";")
    (tmp_path / "index.html").write_text('<script src="data.js"></script>')

    html = mockup(tmp_path)

    assert '"trigger": "<\\/script>"' in html
    assert html.count("</script>") == 1


def _board() -> dict:
    task = {
        "id": "PROJ-2202",
        "title": SECRET,
        "lane": "waiting",
        "milestone": "m-7",
        "labels": ["vm-only", "kind-execute", "needs-human"],
        "assignee": "@agent-deep-high",
        "dependencies": ["PROJ-3000"],
        "prs": [
            {"number": 2404, "checks": "pass", "merged": False, "threads": 1, "url": "https://example.test/pr/2404"}
        ],
        "live": {"machine": "delivering", "state": "ci", "at": 5.0},
        "moves": {"ready": {"allowed": True, "skill": ""}, "review": {"allowed": False, "skill": "completing-tasks"}},
        "entered": 4.0,
        "description": SECRET,
    }
    blocker = {**task, "id": "PROJ-3000", "dependencies": [], "prs": [], "assignee": "Jane Doe", "live": None}
    return {"now": 6.0, "names": {"waiting": "Waiting"}, "tasks": [task, blocker]}


def test_scrub_board_renames_like_the_mockup_board_and_numbers_the_rest_on() -> None:
    demo = scrub_board(_board(), {"PROJ-2201": "DEMO-1", "PROJ-2202": "DEMO-2"})

    task, blocker = demo["tasks"]
    assert (task["id"], blocker["id"], task["dependencies"]) == ("DEMO-2", "DEMO-3", ["DEMO-3"])
    assert task["title"] in TITLES and blocker["title"] in TITLES
    assert task["labels"] == ["kind-execute", "needs-human"]
    assert task["prs"] == [{"number": 1, "checks": "pass", "merged": False, "threads": 1}]
    assert (task["assignee"], blocker["assignee"]) == ("@agent-deep-high", "")
    assert {k: task[k] for k in ("lane", "milestone", "live", "moves", "entered")} == {
        k: _board()["tasks"][0][k] for k in ("lane", "milestone", "live", "moves", "entered")
    }
    assert "description" not in task and (demo["now"], demo["names"]) == (6.0, {"waiting": "Waiting"})
    assert SECRET not in json.dumps(demo)


def test_scrub_board_drops_a_dependency_off_the_board() -> None:
    board = _board()
    board["tasks"][1]["dependencies"] = ["PROJ-9999"]

    assert scrub_board(board, {})["tasks"][1]["dependencies"] == []


def test_scrub_board_refuses_a_key_it_does_not_know() -> None:
    with pytest.raises(ValueError, match="secrets"):
        scrub_board({**_board(), "secrets": []}, {})


def test_mockup_inlines_its_board_renamed_like_its_data(tmp_path: Path) -> None:
    (tmp_path / "data.js").write_text("window.SNAP = " + json.dumps(_snap()) + ";\n")
    (tmp_path / "board.js").write_text("// saved Board\nwindow.BOARD = " + json.dumps(_board()) + ";\n")
    (tmp_path / "index.html").write_text('<script src="data.js"></script><script src="board.js"></script>')

    html = mockup(tmp_path)

    board = json.dumps(scrub_board(_board(), {"PROJ-2201": "DEMO-1", "PROJ-2202": "DEMO-2"})).replace("</", "<\\/")
    assert f"<script>window.BOARD = {board};</script>" in html
    assert "PROJ-" not in html and SECRET not in html


def _machine(initial: str, edges: list[tuple[str, str, str]], final: str = "") -> dict:
    states = dict.fromkeys(x for s, t, _ in edges for x in (s, t))
    return {
        "states": [{"id": s, "name": s, "initial": s == initial, "final": s == final} for s in states],
        "transitions": [{"source": s, "target": t, "event": e} for s, t, e in edges],
    }


BOARD = _machine(
    "new",
    [
        ("new", "ready", "CREATE_READY"),
        ("new", "in_progress", "CREATE_IN_PROGRESS"),
        ("ready", "in_progress", "CLAIM"),
        ("in_progress", "in_progress", "PR_OPENED"),
        ("in_progress", "review", "REVIEW"),
        ("review", "in_progress", "SEND_BACK"),
    ],
)
DELIVERY = _machine(
    "start",
    # green -> red is a move back, so a delivery trail sent back would show it
    [("start", "red", "RED"), ("red", "green", "GREEN"), ("green", "red", "FAIL"), ("green", "done", "DONE")],
    final="done",
)


def _structured(board: list[dict], placed: list[dict]) -> dict:
    live = _live()
    live["flows"] = [
        {
            "name": "board",
            "machine": BOARD
            | {"subflows": [{"state": "in_progress", "flow": "in-progress"}], "mainLine": ["new", "ready"]},
            "agents": board,
        },
        {"name": "in-progress", "machine": DELIVERY, "agents": placed},
    ]
    live["now"] = 100_000.0
    return live


def test_scrub_embeds_each_board_tasks_lane_path_ending_in_its_lane() -> None:
    live = _structured(
        [{"id": "TASK-D1", "state": "review"}, {"id": "TASK-D2", "state": "ready"}, {"id": "TASK-D3", "state": "new"}],
        [],
    )

    history = scrub(live)["history"]

    assert history == {
        # through Ready, not the CREATE_IN_PROGRESS shortcut, three hours apart and ending before `now`
        "DEMO-1": [
            {"at": 67_600.0, "from": None, "to": "ready"},
            {"at": 78_400.0, "from": "ready", "to": "in_progress"},
            {"at": 89_200.0, "from": "in_progress", "to": "review"},
        ],
        # the next task's steps spread half an hour wider and ten minutes earlier
        "DEMO-2": [{"at": 86_800.0, "from": None, "to": "ready"}],
        "DEMO-3": [],
    }


def test_scrub_sends_every_second_board_task_back_a_lane_once_so_the_demo_draws_backtracks() -> None:
    live = _structured([{"id": f"TASK-{n}", "state": "review"} for n in (1, 2, 3, 4)], [])

    history = scrub(live)["history"]

    assert [h["to"] for h in history["DEMO-1"]] == ["ready", "in_progress", "review"]
    # sent back from Review on the machine's own SEND_BACK, then reviewed again, still ending in its lane
    assert [(h["from"], h["to"]) for h in history["DEMO-2"]] == [
        (None, "ready"),
        ("ready", "in_progress"),
        ("in_progress", "review"),
        ("review", "in_progress"),
        ("in_progress", "review"),
    ]
    assert [h["at"] for h in history["DEMO-2"]] == sorted(h["at"] for h in history["DEMO-2"])
    assert [h["to"] for h in history["DEMO-3"]] == ["ready", "in_progress", "review"]
    assert [h["to"] for h in history["DEMO-4"]] == ["ready", "in_progress", "review", "in_progress", "review"]


def test_send_back_splices_the_move_back_mid_route_and_keeps_the_rest_of_the_route() -> None:
    machine = {
        "states": [{"id": "a", "initial": True}, {"id": "b"}, {"id": "c"}, {"id": "d"}],
        "transitions": [
            {"source": "a", "event": "X", "target": "b"},
            {"source": "b", "event": "Y", "target": "c"},
            {"source": "c", "event": "Z", "target": "d"},
            {"source": "c", "event": "BACK", "target": "b"},
        ],
    }
    steps = [("a", "X", "b"), ("b", "Y", "c"), ("c", "Z", "d")]

    assert _send_back(machine, steps) == [
        ("a", "X", "b"),
        ("b", "Y", "c"),
        ("c", "BACK", "b"),
        ("b", "Y", "c"),
        ("c", "Z", "d"),
    ]


def test_scrub_seeds_the_delivery_machine_with_the_in_progress_board_tasks_when_it_has_none() -> None:
    board = [
        {"id": "TASK-D1", "state": "in_progress", "model": "@agent-deep-high"},
        {"id": "TASK-D2", "state": "ready"},
        {"id": "TASK-D3", "state": "in_progress", "model": ""},
        {"id": "TASK-D4", "state": "in_progress", "model": ""},
    ]

    demo = scrub(_structured(board, []))

    assert demo["flows"][1]["agents"] == [
        {
            "id": "DEMO-1",
            "title": TITLES[0],
            "task": "DEMO-1",
            "state": "red",
            "model": "@agent-deep-high",
            "steps": 1,
            "trail": [{"state": "red", "event": "RED", "at": 89_200.0}],
            "active": 89_200.0,
        },
        {
            "id": "DEMO-3",
            "title": TITLES[2],
            "task": "DEMO-3",
            "state": "green",
            "model": "",
            "steps": 2,
            "trail": [
                {"state": "red", "event": "RED", "at": 74_200.0},
                {"state": "green", "event": "GREEN", "at": 86_800.0},
            ],
            "active": 86_800.0,
        },
        # the third wraps round to the first inner state, never the final one
        {
            "id": "DEMO-4",
            "title": TITLES[3],
            "task": "DEMO-4",
            "state": "red",
            "model": "",
            "steps": 1,
            "trail": [{"state": "red", "event": "RED", "at": 84_400.0}],
            "active": 84_400.0,
        },
    ]


def test_scrub_leaves_a_delivery_machine_the_capture_placed_tasks_on() -> None:
    placed = [
        {"id": "TASK-D1", "task": "TASK-D1", "title": "t", "state": "green", "model": "", "steps": 0, "trail": []}
    ]

    demo = scrub(_structured([{"id": "TASK-D1", "state": "in_progress"}], placed))

    assert [a["state"] for a in demo["flows"][1]["agents"]] == ["green"]


def test_scrub_seeds_nothing_when_the_capture_lacks_the_boards_delivery_flow() -> None:
    live = _structured([{"id": "TASK-D1", "state": "in_progress"}], [])
    live["flows"] = live["flows"][:1]

    demo = scrub(live)

    assert [f["name"] for f in demo["flows"]] == ["board"]


def test_scrub_sizes_the_demo_suns_from_its_own_week_of_lane_changes() -> None:
    live = _structured(
        [{"id": "TASK-D1", "state": "review"}, {"id": "TASK-D2", "state": "ready"}, {"id": "TASK-D3", "state": "new"}],
        [],
    )

    suns = scrub(live).get("suns")

    # the six lane ends of the synthetic history above: ready 3, in progress 2, review 1
    assert suns is not None
    assert (suns["ready"], suns["in_progress"], suns["review"]) == pytest.approx((3 / 6, 2 / 6, 1 / 6))
    assert sum(suns.values()) == pytest.approx(1)


def test_scrub_keeps_the_suns_a_capture_reports() -> None:
    live = _structured([{"id": "TASK-D1", "state": "review"}], [])
    live["suns"] = {"ready": 0.25, "review": 0.75}

    assert scrub(live)["suns"] == {"ready": 0.25, "review": 0.75}


def test_scrub_sizes_the_suns_itself_when_the_capture_saw_no_moves() -> None:
    live = _structured(
        [{"id": "TASK-D1", "state": "review"}, {"id": "TASK-D2", "state": "ready"}, {"id": "TASK-D3", "state": "new"}],
        [],
    )
    live["suns"] = {state["id"]: 0.0 for state in BOARD["states"]}  # a fresh server's all-zero shares

    suns = scrub(live)["suns"]

    assert suns["ready"] == pytest.approx(3 / 6)


def test_elements_inlines_the_local_stylesheet_and_script_and_leaves_a_remote_link(tmp_path: Path) -> None:
    (tmp_path / "up").mkdir()
    (tmp_path / "up/real.css").write_text("/* TASK-1 */ :root { --ok: #34d399; }")
    (tmp_path / "sheet").mkdir()
    (tmp_path / "sheet/index.html").write_text(
        '<link rel="stylesheet" href="../up/real.css"><link rel="stylesheet" href="https://x.test/f.css">'
        '<script src="sheet.js"></script>'
    )
    (tmp_path / "sheet/sheet.js").write_text("const s = '</script>';")
    html = elements(tmp_path / "sheet")
    assert "<style> :root { --ok: #34d399; }</style>" in html  # the comment is dropped
    assert '<link rel="stylesheet" href="https://x.test/f.css">' in html
    assert "<script>const s = '<\\/script>';</script>" in html
