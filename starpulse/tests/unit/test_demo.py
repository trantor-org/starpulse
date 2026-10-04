"""The self-contained demo page: live structure, synthetic agents, one file."""

import io
import json
import re
import urllib.request
from pathlib import Path

import pytest

from starpulse.demo import TITLES, capture, mockup, page, scrub, scrub_mockup

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
        "settled": {"PROJ-2100": "completed"},
        "error": "ci: down",
        "now": 1.0,
    }


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
        "title": TITLES[0],
        "state": "ready",
        "model": "",
        "milestone": "",
        "labels": [],
        "dependencies": [],
        "description": f"Synthetic demo task: {TITLES[0].lower()}.",
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
    }
    assert board[3]["dependencies"] == ["DEMO-1"] and board[3]["labels"] == ["size-5", "needs-human"]
    assert demo["pulls"]["DEMO-9"] == [
        {"number": 108, "url": "#", "checks": "pass", "merged": False, "threads": 2, "stale": False}
    ]
    assert demo["pulls"]["DEMO-12"][0]["merged"] is True
    assert set(demo["pulls"]) <= {a["id"] for a in board}
    assert not re.search(r"PROJ-\d|github\.com", json.dumps(demo))


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
