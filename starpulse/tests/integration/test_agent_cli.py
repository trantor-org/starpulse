"""`starpulse snapshot|board|task show|help --agent`: an agent reads the running server and gets one JSON document."""

import json
import re
import socket
import threading
import time
import urllib.request
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from starpulse import agent_cli as cli
from starpulse import doctor, skill_install
from starpulse.adapter_kit import serve as _serve
from starpulse.adapter_kit import task
from starpulse.adapter_kit import url as _url
from starpulse.board import Written
from starpulse.board_feed import BoardFeed
from starpulse.contracts import Move
from starpulse.history import HistoryStore
from starpulse.server import _no_writer
from starpulse.tests.hosts import FakeHost
from starpulse.tests.machines import MACHINES

PULL = "https://github.com/acme/app/pull/5"
UNREAD_PULL = "https://github.com/acme/app/pull/9"  # linked from a task, but the server has not read it


def _dag(name: str, status: str, raw: str | None = None) -> dict[str, Any]:
    """A workflow as a runs adapter lists it."""
    return {
        "name": name,
        "status": status,
        "raw": raw,
        "runId": f"{name}-1",
        "startedAt": "2026-10-05T17:00:00Z",
        "finishedAt": "",
        "steps": [],
    }


def _run(
    capsys: pytest.CaptureFixture[str], argv: Sequence[str], environ: dict[str, str] | None = None
) -> tuple[int, Any]:
    """The exit code and the one JSON document on stdout; a second document, or any stderr, fails the test."""
    code = cli.main(argv, environ or {})
    out = capsys.readouterr()
    assert out.err == ""
    return code, json.loads(out.out)


@pytest.fixture
def base(tmp_path: Path) -> Iterator[str]:
    """A server's address, its Board holding four open tasks and one completed."""
    feed = BoardFeed(machines=MACHINES)
    feed.put(
        task(
            "PROJ-1",
            "To Do",
            milestone="m-1",
            labels=("cli",),
            assignee="@agent-a",
            dependencies=("PROJ-2", "PROJ-3"),
            references=(PULL, "docs/plan.md"),
            description="Add the verbs.",
            moves={
                "in_progress": Move(allowed=False, reason="claim it first", skill="starting-tasks"),
                "ready": Move(allowed=True),
            },
        )
    )
    feed.put(
        task("PROJ-2", "Ready", milestone="m-2", labels=("api", "cli"), assignee="@agent-b", references=(UNREAD_PULL,))
    )
    feed.put(task("PROJ-3", "Done", settled="completed"))
    feed.put(task("PROJ-4", "In Progress", milestone="m-2", labels=("api",), assignee="@agent-a"))
    feed.put(task("PROJ-5", "Ready"))
    pull = {"number": 5, "url": PULL, "checks": "pass", "merged": False, "threads": 2, "stale": False}
    feed.set_pulls({"PROJ-1": [pull]})
    for task_id, state in (("PROJ-1", "worktree_ready"), ("PROJ-2", "worktree_ready"), ("PROJ-4", "green")):
        feed.move(
            "in-progress",
            {
                "id": task_id,
                "title": task_id,
                "model": "",
                "task": task_id,
                "state": state,
                "steps": 1,
                "trail": [],
                "active": time.time(),
            },
        )
    feed.runs("prod").set_dags([_dag("nightly", "succeeded", "Success"), _dag("backup", "running")], None)
    feed.runs("staging").set_dags([_dag("nightly", "failed")], "listing was refused")
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)
    for i, event in enumerate(["WORKTREE_READY", "RED_PROVEN"]):
        store.record_machine(
            f"m{i}-0",
            {"event_id": f"m{i}", "machine": "in-progress", "event": event, "task": "PROJ-1", "time": 100.0 + i},
        )
    for i, lane in enumerate(("to_do", "ready")):
        store.record_lane(f"l{i}", "PROJ-1", lane, 200.0 + i)
    with _serve(tmp_path, feed, history=store) as server:
        yield _url(server, "")


class _Writer:
    """A board writer that records each status change with its actor and answers with one canned reply."""

    def __init__(self) -> None:
        self.reply = Written(True, "Updated")
        self.sent: list[tuple[str, str, str]] = []
        self.sessions: list[str] = []

    def __call__(self, task: str, status: str, actor: str, session: str = "") -> Written:
        self.sent.append((task, status, actor))
        self.sessions.append(session)
        return self.reply


@pytest.fixture
def writer() -> _Writer:
    return _Writer()


def _moving_board() -> BoardFeed:
    """One In Progress task: Ready is the operator's alone, Review anyone's, Waiting a guarded column."""
    feed = BoardFeed(machines=MACHINES)
    feed.put(
        task(
            "PROJ-6",
            "In Progress",
            moves={
                "ready": Move(
                    allowed=True,
                    writers=("operator",),
                    reason="only the operator sends a task back",
                    skill="operating-the-board",
                ),
                "review": Move(allowed=True, writers=("agent", "operator")),
                "waiting": Move(allowed=False, reason="name what it waits on", skill="parking-tasks"),
            },
        )
    )
    return feed


@pytest.fixture
def movable(tmp_path: Path, writer: _Writer) -> Iterator[str]:
    """A server whose board writer answers, holding `_moving_board`."""
    with _serve(tmp_path, _moving_board(), writer=writer) as server:
        yield _url(server, "")


@pytest.fixture
def bare(tmp_path: Path) -> Iterator[str]:
    """A server with `_moving_board` and no board writer, as one with no `[board]` adapter that writes."""
    with _serve(tmp_path, _moving_board(), writer=_no_writer) as server:
        yield _url(server, "")


@pytest.fixture(autouse=True)
def healthy_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """`doctor` probes this fake host, not the machine the suite runs on."""
    monkeypatch.setattr(doctor, "LIVE", FakeHost().probes())


def _closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


def test_an_unreachable_server_exits_3_naming_the_url_it_tried(capsys: pytest.CaptureFixture[str]) -> None:
    down = _closed_port_url()

    code, doc = _run(capsys, ["snapshot", "--server", down])

    assert code == 3
    assert doc["code"] == "unavailable"
    assert doc["error"].startswith(f"cannot reach StarPulse at {down}")


def test_a_server_that_answers_an_error_status_is_unavailable_and_named(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["snapshot", "--server", f"{base}/elsewhere"])

    assert code == 3
    assert doc == {
        "error": f"{base}/elsewhere answered 404 for /api/snapshot: is it a StarPulse server?",
        "code": "unavailable",
    }


@pytest.mark.parametrize("body", [b"[]", b'{"ok": true}'])
@pytest.mark.parametrize("verb", [["snapshot"], ["board"], ["task", "show", "PROJ-1"]])
def test_a_server_that_answers_json_that_is_no_snapshot_is_unavailable(
    body: bytes, verb: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    class Other(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Other) as other:
        threading.Thread(target=other.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{other.server_address[1]}"
        try:
            code, doc = _run(capsys, [*verb, "--server", base])
        finally:
            other.shutdown()

    assert code == 3
    assert doc == {
        "error": f"{base} answered /api/snapshot with no StarPulse snapshot: is it a StarPulse server?",
        "code": "unavailable",
    }


@pytest.mark.parametrize(
    ("flag", "env", "expected"),
    [
        ("http://flag:1", {"STARPULSE_URL": "http://env:2"}, "http://flag:1"),
        (None, {"STARPULSE_URL": "http://env:2"}, "http://env:2"),
        (None, {}, "http://localhost:8766"),
        ("http://flag:1/", {}, "http://flag:1"),
        ("http://proxy/api-X/", {}, "http://proxy/api-X"),
    ],
)
def test_the_server_is_the_flag_else_the_environment_else_the_default_port(
    flag: str | None, env: dict[str, str], expected: str
) -> None:
    assert cli.server_url(flag, env) == expected


@pytest.mark.parametrize("argv", [["snapshot"], ["board"], ["task", "show", "PROJ-1"]])
def test_a_verb_without_a_server_flag_reads_the_server_the_environment_names(
    base: str, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    code, _ = _run(capsys, argv, {"STARPULSE_URL": base})

    assert code == 0


def test_the_snapshot_verb_prints_the_servers_snapshot(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["snapshot", "--server", base])
    with urllib.request.urlopen(f"{base}/api/snapshot", timeout=5) as resp:
        served = json.load(resp)

    assert code == 0
    assert doc.pop("now") <= served.pop("now")
    assert doc == served


def test_the_board_lists_each_column_with_its_tasks_dependencies_prs_and_moves(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["board", "--server", base])

    assert code == 0
    assert [(c["state"], c["name"], [t["id"] for t in c["tasks"]]) for c in doc["columns"]] == [
        ("to_do", "To Do", ["PROJ-1"]),
        ("ready", "Ready", ["PROJ-2", "PROJ-5"]),
        ("in_progress", "In Progress", ["PROJ-4"]),
        ("review", "Review", []),
        ("done", "Done", []),
    ]
    assert doc["columns"][0]["tasks"][0] == {
        "id": "PROJ-1",
        "title": "Title of PROJ-1",
        "lane": "to_do",
        "assignee": "@agent-a",
        "milestone": "m-1",
        "labels": ["cli"],
        "dependencies": ["PROJ-2", "PROJ-3"],
        "waiting_on": ["PROJ-2"],
        "prs": [{"number": 5, "url": PULL, "checks": "pass", "merged": False, "threads": 2, "stale": False}],
        "moves": {
            "in_progress": {"allowed": False, "reason": "claim it first", "skill": "starting-tasks"},
            "ready": {"allowed": True, "reason": "", "skill": ""},
        },
    }


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (["--state", "ready"], ["PROJ-2", "PROJ-5"]),
        (["--milestone", "m-2"], ["PROJ-2", "PROJ-4"]),
        (["--label", "cli"], ["PROJ-1", "PROJ-2"]),
        (["--assignee", "@agent-a"], ["PROJ-1", "PROJ-4"]),
        (["--milestone", "m-2", "--label", "api", "--assignee", "@agent-a"], ["PROJ-4"]),
        (["--milestone", "m-9"], []),
    ],
)
def test_the_board_keeps_only_the_tasks_every_filter_matches(
    base: str, capsys: pytest.CaptureFixture[str], filters: list[str], expected: list[str]
) -> None:
    code, doc = _run(capsys, ["board", *filters, "--server", base])

    assert code == 0
    assert [t["id"] for c in doc["columns"] for t in c["tasks"]] == expected


def test_a_state_filter_leaves_only_that_column(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    _, doc = _run(capsys, ["board", "--state", "ready", "--server", base])

    assert [c["state"] for c in doc["columns"]] == ["ready"]


def test_a_state_the_board_does_not_have_is_a_usage_error_naming_the_states(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["board", "--state", "nowhere", "--server", base])

    assert (code, doc["code"]) == (2, "usage")
    assert doc["error"] == "unknown state nowhere; the board has to_do, ready, in_progress, review, done"


def test_an_unknown_flag_is_a_usage_error_that_names_it(capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["snapshot", "--nope"])

    assert (code, doc["code"]) == (2, "usage")
    assert "--nope" in doc["error"]


def test_a_pull_request_the_server_has_not_read_is_reported_by_its_link(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _, doc = _run(capsys, ["task", "show", "PROJ-2", "--server", base])

    assert doc["prs"] == [{"url": UNREAD_PULL}]


def test_task_show_gives_the_lane_dependencies_what_it_waits_on_prs_and_moves(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "show", "PROJ-1", "--server", base])

    assert code == 0
    assert doc["lane"] == "to_do"
    assert doc["description"] == "Add the verbs."
    assert doc["dependencies"] == ["PROJ-2", "PROJ-3"]
    assert doc["waiting_on"] == ["PROJ-2"]  # PROJ-3 is completed
    assert doc["prs"][0]["threads"] == 2
    assert doc["moves"]["in_progress"] == {"allowed": False, "reason": "claim it first", "skill": "starting-tasks"}


def test_task_show_reports_a_settled_task_by_where_it_settled(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "show", "PROJ-3", "--server", base])

    assert code == 0
    assert doc == {
        "id": "PROJ-3",
        "title": "",
        "lane": "completed",
        "assignee": "",
        "milestone": "",
        "labels": [],
        "dependencies": [],
        "waiting_on": [],
        "prs": [],
        "moves": {},
        "description": "",
    }


def test_a_task_the_board_does_not_hold_is_not_found(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "show", "PROJ-99", "--server", base])

    assert (code, doc["code"]) == (4, "not_found")
    assert "PROJ-99" in doc["error"]


def test_task_moves_lists_every_target_with_the_verdict_the_agent_meets(
    movable: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "moves", "PROJ-6", "--server", movable])

    assert code == 0
    assert doc == {
        "task": "PROJ-6",
        "lane": "in_progress",
        "moves": {
            "ready": {
                "allowed": False,
                "reason": "only the operator sends a task back",
                "skill": "operating-the-board",
            },
            "review": {"allowed": True, "reason": "", "skill": ""},
            "waiting": {"allowed": False, "reason": "name what it waits on", "skill": "parking-tasks"},
        },
    }


def test_a_move_whose_writers_leave_out_the_agent_is_refused_to_it_with_a_reason_even_when_unguarded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-7", "In Progress", moves={"ready": Move(allowed=True, writers=("operator",))}))
    with _serve(tmp_path, feed) as server:
        _, doc = _run(capsys, ["task", "moves", "PROJ-7", "--server", _url(server, "")])

    assert doc["moves"] == {"ready": {"allowed": False, "reason": "made by operator, not agent", "skill": ""}}


def test_task_move_of_an_in_progress_task_to_ready_is_refused_to_the_agent_but_the_operator_may(
    movable: str, writer: _Writer, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "move", "PROJ-6", "ready", "--server", movable])

    assert code == 1
    assert doc == {
        "ok": False,
        "task": "PROJ-6",
        "to": "ready",
        "reason": "only the operator sends a task back",
        "skill": "operating-the-board",
        "advice": "",
    }
    assert writer.sent == []  # refused before the board was asked
    post = urllib.request.Request(
        f"{movable}/api/move", data=json.dumps({"task": "PROJ-6", "to": "ready"}).encode(), method="POST"
    )
    with urllib.request.urlopen(post, timeout=5) as response:
        assert response.status == 200
    assert writer.sent == [("PROJ-6", "Ready", "operator")]


def test_task_move_writes_as_the_agent_and_reports_the_move(
    movable: str, writer: _Writer, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "move", "PROJ-6", "review", "--server", movable])

    assert code == 0
    assert doc == {"ok": True, "task": "PROJ-6", "to": "review", "reason": "", "skill": "", "advice": ""}
    assert writer.sent == [("PROJ-6", "Review", "agent")]


def test_task_move_names_the_session_from_its_flag_or_the_environment_and_reports_the_advice(
    movable: str, writer: _Writer, capsys: pytest.CaptureFixture[str]
) -> None:
    writer.reply = Written(True, "Updated", advice="PROJ-6 is size-8: advised profile @agent-deep-high")

    code, doc = _run(capsys, ["task", "move", "PROJ-6", "review", "--server", movable, "--session", "from-flag"])

    assert code == 0
    assert doc["advice"] == "PROJ-6 is size-8: advised profile @agent-deep-high"
    environ = {"STARPULSE_SESSION": "from-env"}
    _run(capsys, ["task", "move", "PROJ-6", "review", "--server", movable], environ)
    _run(capsys, ["task", "move", "PROJ-6", "review", "--server", movable, "--session", "from-flag"], environ)
    assert writer.sessions == ["from-flag", "from-env", "from-flag"]


def test_task_move_with_no_session_and_no_advice_sends_no_session_and_reports_empty_advice(
    movable: str, writer: _Writer, capsys: pytest.CaptureFixture[str]
) -> None:
    _, doc = _run(capsys, ["task", "move", "PROJ-6", "review", "--server", movable])

    assert doc["advice"] == ""
    assert writer.sessions == [""]


def test_a_move_the_board_writer_refuses_exits_1_with_its_reason_and_skill(
    movable: str, writer: _Writer, capsys: pytest.CaptureFixture[str]
) -> None:
    writer.reply = Written(False, "refusing to set PROJ-6 Waiting: name what it waits on", "parking-tasks")

    code, doc = _run(capsys, ["task", "move", "PROJ-6", "waiting", "--server", movable])

    assert code == 1
    assert (doc["ok"], doc["reason"], doc["skill"]) == (
        False,
        "refusing to set PROJ-6 Waiting: name what it waits on",
        "parking-tasks",
    )


def test_a_column_the_task_cannot_move_to_is_a_refusal_naming_it(
    movable: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "move", "PROJ-6", "done", "--server", movable])

    assert (code, doc["ok"], doc["reason"]) == (1, False, "PROJ-6 cannot move from in_progress to done")


def test_task_move_on_a_board_with_no_writer_exits_3_and_says_so(bare: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "move", "PROJ-6", "review", "--server", bare])

    assert code == 3
    assert doc["code"] == "unavailable"
    assert "no board writer is configured" in doc["error"]


def test_no_verb_is_a_usage_error_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, [])

    assert (code, doc["code"]) == (2, "usage")


def test_the_manifest_lists_each_verbs_arguments_outputs_and_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["help", "--agent"])

    assert code == 0
    assert doc["exit_codes"] == {
        "0": "ok",
        "1": "refused or invalid",
        "2": "usage",
        "3": "unavailable",
        "4": "not found",
    }
    board = next(v for v in doc["verbs"] if v["verb"] == "board")
    flags = {flag for arg in board["arguments"] for flag in arg["flags"]}
    assert {"--state", "--milestone", "--label", "--assignee", "--server"} <= flags
    assert board["exit_codes"] == [0, 2, 3]
    assert "columns" in board["outputs"]
    show = next(v for v in doc["verbs"] if v["verb"] == "task show")
    assert [(a["name"], a["required"]) for a in show["arguments"] if not a["flags"]] == [("task", True)]


def test_the_manifest_describes_every_verb_and_each_of_its_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    _, doc = _run(capsys, ["help", "--agent"])

    assert [v["verb"] for v in doc["verbs"]] == [
        "snapshot",
        "board",
        "task show",
        "task moves",
        "task move",
        "task trace",
        "machine list",
        "machine show",
        "runs list",
        "runs start",
        "watch",
        "analytics health",
        "doctor",
        "skills list",
        "skills install",
        "help",
    ]
    for verb in doc["verbs"]:
        assert verb["summary"]
        assert all(set(a) == {"name", "flags", "required", "help"} for a in verb["arguments"])
        assert all(a["help"] for a in verb["arguments"]), verb["verb"]
        assert "help" not in {a["name"] for a in verb["arguments"]}  # argparse's own -h is not a verb argument
    board = next(v for v in doc["verbs"] if v["verb"] == "board")
    state = next(a for a in board["arguments"] if a["name"] == "state")
    assert (state["flags"], state["required"]) == (["--state"], False)
    manifest = next(v for v in doc["verbs"] if v["verb"] == "help")
    assert [(a["name"], a["flags"], a["required"]) for a in manifest["arguments"]] == [("agent", ["--agent"], True)]


def test_machine_list_names_each_machine_with_its_states_and_live_task_count(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["machine", "list", "--server", base])

    assert code == 0
    assert [(m["name"], m["tasks"]) for m in doc["machines"]] == [
        ("board", 4),
        ("in-progress", 3),
        ("authoring-skills", 0),
    ]
    assert doc["machines"][0]["states"] == ["to_do", "ready", "in_progress", "review", "done"]


def test_machine_show_gives_states_transitions_and_the_live_tasks_per_state(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["machine", "show", "in-progress", "--server", base])
    with urllib.request.urlopen(f"{base}/api/snapshot", timeout=5) as resp:
        drawn = next(f["machine"] for f in json.load(resp)["flows"] if f["name"] == "in-progress")

    assert code == 0
    assert doc["name"] == "in-progress"
    assert doc["transitions"] == drawn["transitions"]
    assert [(s["id"], s["name"], s["initial"], s["final"]) for s in doc["states"]] == [
        (s["id"], s["name"], s["initial"], s["final"]) for s in drawn["states"]
    ]
    live = {s["id"]: (s["count"], s["tasks"]) for s in doc["states"]}
    assert live["worktree_ready"] == (2, ["PROJ-1", "PROJ-2"])
    assert live["green"] == (1, ["PROJ-4"])
    assert live["start"] == (0, [])


def test_machine_show_counts_the_boards_open_tasks_per_column(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    _, doc = _run(capsys, ["machine", "show", "board", "--server", base])

    assert {s["id"]: (s["count"], s["tasks"]) for s in doc["states"]} == {
        "to_do": (1, ["PROJ-1"]),
        "ready": (2, ["PROJ-2", "PROJ-5"]),
        "in_progress": (1, ["PROJ-4"]),
        "review": (0, []),
        "done": (0, []),  # PROJ-3 settled: it left the lanes
    }


def test_a_machine_the_server_does_not_draw_is_not_found_naming_the_machines(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["machine", "show", "nowhere", "--server", base])

    assert (code, doc["code"]) == (4, "not_found")
    assert doc["error"] == "nowhere is not a machine; the server draws board, in-progress, authoring-skills"


def test_task_trace_without_a_flow_is_the_boards_lane_path(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "trace", "PROJ-1", "--server", base])

    assert code == 0
    assert doc == {
        "task": "PROJ-1",
        "flow": None,
        "path": [{"at": 200.0, "from": None, "to": "to_do"}, {"at": 201.0, "from": "to_do", "to": "ready"}],
        "steps": 2,
    }


def test_task_trace_with_a_flow_is_the_machine_path(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "trace", "PROJ-1", "--flow", "in-progress", "--server", base])

    assert code == 0
    assert doc == {
        "task": "PROJ-1",
        "flow": "in-progress",
        "path": [
            {"at": 100.0, "event": "WORKTREE_READY", "state": "worktree_ready"},
            {"at": 101.0, "event": "RED_PROVEN", "state": "red_proven"},
        ],
        "steps": 2,
    }


def test_task_trace_of_a_task_never_seen_is_an_empty_path(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "trace", "PROJ-99", "--server", base])

    assert (code, doc["path"], doc["steps"]) == (0, [], 0)


def test_task_trace_of_an_unknown_flow_is_not_found(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "trace", "PROJ-1", "--flow", "nowhere", "--server", base])

    assert (code, doc) == (4, {"error": "unknown flow nowhere", "code": "not_found"})


def test_analytics_health_reports_the_boards_flow_health_with_a_stay_still_open_counted_to_now(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", "health", "--hours", "24", "--stuck-hours", "1", "--server", base])

    states = {state["id"]: state for state in doc["states"]}
    assert code == 0
    assert (doc["window_s"], doc["stuck_after_s"], doc["warnings"]) == (24 * 3600, 3600, [])
    assert (states["ready"]["wip"], states["ready"]["open"], states["to_do"]["visits"]) == (1, 1, 0)
    assert doc["throughput"] == {"count": 0, "per_day": 0.0}
    (stuck,) = doc["stuck"]  # PROJ-1 entered Ready at second 201 and is still there
    assert (stuck["task"], stuck["state"], stuck["since"], stuck["counted_to_now"]) == ("PROJ-1", "ready", 201.0, True)
    assert stuck["dwell_s"] == pytest.approx(doc["now"] - 201.0)


def test_analytics_health_refuses_a_window_the_server_refuses(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["analytics", "health", "--hours", "0", "--server", base])

    assert (code, doc["code"], "positive number" in doc["error"]) == (1, "refused", True)


def test_runs_list_names_each_workflow_by_instance_with_its_status_and_the_runs_error(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["runs", "list", "--server", base])

    assert code == 0
    assert doc["error"] == "staging: listing was refused"
    assert doc["runs"] == [
        {
            "workflow": workflow,
            "status": status,
            "raw": raw,
            "run_id": run_id,
            "started_at": "2026-10-05T17:00:00Z",
            "finished_at": "",
        }
        for workflow, status, raw, run_id in (
            ("prod/nightly", "succeeded", "Success", "nightly-1"),
            ("prod/backup", "running", None, "backup-1"),
            ("staging/nightly", "failed", None, "nightly-1"),
        )
    ]


@pytest.fixture
def runnable(tmp_path: Path) -> Iterator[str]:
    """A server whose `prod` instance can start runs and holds `prod/nightly` run-safe; `staging` has no start."""
    feed = BoardFeed(machines=MACHINES)
    feed.runs("prod").set_dags([_dag("nightly", "succeeded"), _dag("backup", "running")], None)
    feed.runs("staging").set_dags([_dag("nightly", "failed")], None)
    with _serve(
        tmp_path,
        feed,
        starts={"prod": lambda workflow: f"{workflow}-7"},
        run_safe=frozenset({"prod/nightly"}),
    ) as server:
        yield _url(server, "")


@contextmanager
def _canned(status: int, body: dict[str, Any]) -> Iterator[str]:
    """A server that answers every request with `status` and the JSON `body`, as one the run guards refuse."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield _url(server, "")
    finally:
        server.shutdown()


@pytest.fixture
def forbidden() -> Iterator[str]:
    """A server that refuses Run now to the caller, as it does one outside loopback and the private network."""
    with _canned(403, {"error": "Run now answers only loopback and private network (RFC 1918) browsers"}) as base:
        yield base


def test_runs_start_returns_the_run_id_of_a_run_safe_workflow(
    runnable: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["runs", "start", "prod/nightly", "--server", runnable])

    assert (code, doc) == (0, {"workflow": "prod/nightly", "run_id": "nightly-7"})


def test_runs_start_of_an_instance_without_start_exits_3(runnable: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["runs", "start", "staging/nightly", "--server", runnable])

    assert (code, doc["code"]) == (3, "unavailable")
    assert "no adapter can start staging/nightly" in doc["error"]


def test_runs_start_of_a_workflow_outside_run_safe_exits_4(runnable: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["runs", "start", "prod/backup", "--server", runnable])

    assert (code, doc) == (4, {"error": "prod/backup is not declared run-safe", "code": "not_found"})


def test_runs_start_the_server_refuses_to_the_caller_exits_1(
    forbidden: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["runs", "start", "prod/nightly", "--server", forbidden])

    assert (code, doc["code"]) == (1, "refused")
    assert "loopback" in doc["error"]


def test_runs_start_the_adapter_fails_to_start_exits_3_with_its_error(capsys: pytest.CaptureFixture[str]) -> None:
    with _canned(502, {"error": "dagu refused the start"}) as failing:
        code, doc = _run(capsys, ["runs", "start", "prod/nightly", "--server", failing])

    assert (code, doc) == (3, {"error": f"{failing}: dagu refused the start", "code": "unavailable"})


def test_runs_start_without_an_instance_is_a_usage_error(runnable: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["runs", "start", "nightly", "--server", runnable])

    assert (code, doc["code"]) == (2, "usage")
    assert "<instance>/<workflow>" in doc["error"]


# What a watch sees on the stream: the connect snapshot, then one of each delta the server sends.
FLOWS = ("board", "in-progress", "deploy")
DELTAS: list[tuple[str, dict[str, Any]]] = [
    ("task", {"id": "PROJ-1", "agent": {"state": "ready"}, "settled": None}),
    ("task", {"id": "PROJ-2", "agent": {"state": "review"}, "settled": None}),
    ("move", {"flow": "in-progress", "id": "PROJ-1", "agent": {"state": "green"}}),
    ("move", {"flow": "in-progress", "id": "PROJ-2", "agent": {"state": "red"}}),
    ("move", {"flow": "deploy", "id": "PROJ-1", "agent": {"state": "live"}}),
    ("pulls", {"pulls": {"PROJ-1": [{"number": 5}], "PROJ-2": [{"number": 6}]}}),
    ("claim", {"task": "PROJ-2", "reason": "claim it first", "at": 1.0}),
    ("dags", {"dags": [], "error": None}),
]


@contextmanager
def _stream(frames: Sequence[tuple[str, dict[str, Any]]]) -> Iterator[str]:
    """A server whose `/api/events` sends `frames`, with a keep-alive comment between them, then closes the stream."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for name, data in frames:
                self.wfile.write(f": ping\n\nevent: {name}\ndata: {json.dumps(data)}\n\n".encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield _url(server, "")
    finally:
        server.shutdown()


def _watch(
    capsys: pytest.CaptureFixture[str], base: str, *flags: str
) -> tuple[int, list[dict[str, Any]], dict[str, Any]]:
    """A watch of `base` that runs until the server closes the stream: the exit code, the delta lines, the last line."""
    code = cli.main(["watch", "--server", base, *flags], {})
    out = capsys.readouterr()
    assert out.err == ""
    lines = [json.loads(line) for line in out.out.splitlines()]
    return code, lines[:-1], lines[-1]


def _line(index: int) -> dict[str, Any]:
    event, data = DELTAS[index]
    return {"event": event, "data": data}


@pytest.fixture
def stream() -> Iterator[str]:
    with _stream([("snapshot", {"flows": [{"name": flow} for flow in FLOWS]}), *DELTAS]) as base:
        yield base


@pytest.mark.parametrize(
    ("flags", "wanted"),
    [
        ([], [0, 1, 2, 3, 4, 5, 6, 7]),
        (["--machine", "in-progress"], [2, 3]),
        (["--machine", "board"], [0, 1, 5, 6]),
        (["--task", "PROJ-2"], [1, 3, 5, 6]),
        (["--machine", "in-progress", "--task", "PROJ-2"], [3]),
        (["--task", "PROJ-9"], []),
    ],
)
def test_watch_writes_one_json_line_per_matching_delta_and_filters_by_machine_and_task(
    stream: str, capsys: pytest.CaptureFixture[str], flags: list[str], wanted: list[int]
) -> None:
    code, deltas, last = _watch(capsys, stream, *flags)

    expected = [_line(i) for i in wanted]
    for line in expected:  # `--task` keeps only that task's pull requests
        if line["event"] == "pulls" and "--task" in flags:
            task = flags[flags.index("--task") + 1]
            line["data"] = {"pulls": {task: line["data"]["pulls"][task]}}
    assert deltas == expected
    assert (code, last["code"]) == (3, "unavailable")  # the server closing the stream is the watch's only end
    assert "closed the event stream" in last["error"]


def test_watch_never_writes_the_connect_snapshot(stream: str, capsys: pytest.CaptureFixture[str]) -> None:
    _, deltas, _ = _watch(capsys, stream)

    assert "snapshot" not in {line["event"] for line in deltas}


def test_watch_of_an_unknown_machine_is_not_found_before_any_delta(
    stream: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["watch", "--machine", "nowhere", "--server", stream], {})
    out = capsys.readouterr()

    assert code == 4
    assert json.loads(out.out) == {
        "error": "nowhere is not a machine; the server draws board, in-progress, deploy",
        "code": "not_found",
    }


def test_watch_of_a_server_that_is_no_event_stream_is_unavailable(capsys: pytest.CaptureFixture[str]) -> None:
    with _stream([("task", DELTAS[0][1])]) as base:  # the first event is no snapshot
        code = cli.main(["watch", "--server", base], {})

    assert (code, json.loads(capsys.readouterr().out)["code"]) == (3, "unavailable")


def test_an_interrupt_ends_a_watch_with_exit_0_after_the_lines_it_wrote(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def frames(base: str) -> Iterator[tuple[str, dict[str, Any]]]:
        yield "snapshot", {"flows": [{"name": "board"}]}
        yield DELTAS[0]
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_frames", frames)

    code = cli.main(["watch"], {})
    out = capsys.readouterr()

    assert code == 0
    assert [json.loads(line) for line in out.out.splitlines()] == [_line(0)]
    assert out.err == ""


# Every verb the manifest lists, and each exit code it declares, with an argument line that produces it. `{server}`
# is a running server, `{down}` an address nothing listens on.
CASES = {
    ("snapshot", 0): ["snapshot", "--server", "{server}"],
    ("snapshot", 2): ["snapshot", "--nope"],
    ("snapshot", 3): ["snapshot", "--server", "{down}"],
    ("board", 0): ["board", "--server", "{server}"],
    ("board", 2): ["board", "--state", "nowhere", "--server", "{server}"],
    ("board", 3): ["board", "--server", "{down}"],
    ("analytics health", 0): ["analytics", "health", "--server", "{server}"],
    ("analytics health", 1): ["analytics", "health", "--hours", "0", "--server", "{server}"],
    ("analytics health", 2): ["analytics", "health", "--hours", "soon"],
    ("analytics health", 3): ["analytics", "health", "--server", "{down}"],
    ("task show", 0): ["task", "show", "PROJ-1", "--server", "{server}"],
    ("task show", 2): ["task", "show"],
    ("task show", 3): ["task", "show", "PROJ-1", "--server", "{down}"],
    ("task show", 4): ["task", "show", "PROJ-99", "--server", "{server}"],
    ("task moves", 0): ["task", "moves", "PROJ-6", "--server", "{movable}"],
    ("task moves", 2): ["task", "moves"],
    ("task moves", 3): ["task", "moves", "PROJ-6", "--server", "{down}"],
    ("task moves", 4): ["task", "moves", "PROJ-99", "--server", "{movable}"],
    ("task move", 0): ["task", "move", "PROJ-6", "review", "--server", "{movable}"],
    ("task move", 1): ["task", "move", "PROJ-6", "ready", "--server", "{movable}"],
    ("task move", 2): ["task", "move", "PROJ-6"],
    ("task move", 3): ["task", "move", "PROJ-6", "review", "--server", "{bare}"],
    ("task move", 4): ["task", "move", "PROJ-99", "review", "--server", "{movable}"],
    ("task trace", 0): ["task", "trace", "PROJ-1", "--flow", "in-progress", "--server", "{server}"],
    ("task trace", 2): ["task", "trace"],
    ("task trace", 3): ["task", "trace", "PROJ-1", "--server", "{down}"],
    ("task trace", 4): ["task", "trace", "PROJ-1", "--flow", "nowhere", "--server", "{server}"],
    ("machine list", 0): ["machine", "list", "--server", "{server}"],
    ("machine list", 2): ["machine", "list", "--nope"],
    ("machine list", 3): ["machine", "list", "--server", "{down}"],
    ("machine show", 0): ["machine", "show", "board", "--server", "{server}"],
    ("machine show", 2): ["machine", "show"],
    ("machine show", 3): ["machine", "show", "board", "--server", "{down}"],
    ("machine show", 4): ["machine", "show", "nowhere", "--server", "{server}"],
    ("runs list", 0): ["runs", "list", "--server", "{server}"],
    ("runs list", 2): ["runs", "list", "--nope"],
    ("runs list", 3): ["runs", "list", "--server", "{down}"],
    ("runs start", 0): ["runs", "start", "prod/nightly", "--server", "{runnable}"],
    ("runs start", 1): ["runs", "start", "prod/nightly", "--server", "{forbidden}"],
    ("runs start", 2): ["runs", "start"],
    ("runs start", 3): ["runs", "start", "staging/nightly", "--server", "{runnable}"],
    ("runs start", 4): ["runs", "start", "prod/backup", "--server", "{runnable}"],
    ("watch", 2): ["watch", "--nope"],
    ("watch", 3): ["watch", "--server", "{down}"],
    ("watch", 4): ["watch", "--machine", "nowhere", "--server", "{server}"],
    ("doctor", 0): ["doctor", "--server", "{server}"],
    ("doctor", 1): ["doctor", "--server", "{down}"],
    ("doctor", 2): ["doctor", "--nope"],
    ("skills list", 0): ["skills", "list"],
    ("skills list", 2): ["skills", "list", "--nope"],
    ("skills install", 0): ["skills", "install", "--claude", "--codex"],
    ("skills install", 1): ["skills", "install", "--claude"],
    ("skills install", 2): ["skills", "install"],
    ("help", 0): ["help", "--agent"],
    ("help", 2): ["help"],
}


def _edit_an_installed_copy() -> None:
    """The state `skills install` meets for exit 1: a bundled skill installed here, then edited."""
    skill_install.install(Path.cwd(), ["claude"], force=False)
    (Path.cwd() / ".claude/skills/operating-starpulse-board/SKILL.md").write_text("mine\n")


PREPARE = {("skills install", 1): _edit_an_installed_copy}


def _manifest(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    return _run(capsys, ["help", "--agent"])[1]["verbs"]


# A verb that ends only when interrupted has no case that writes one document; its own test covers that exit.
INTERRUPTED = {("watch", 0)}


def test_every_manifest_verb_and_exit_code_has_a_case(capsys: pytest.CaptureFixture[str]) -> None:
    declared = {(v["verb"], code) for v in _manifest(capsys) for code in v["exit_codes"]}

    assert declared - INTERRUPTED == set(CASES)


@pytest.mark.parametrize(("verb", "exit_code"), list(CASES))
def test_a_manifest_verb_writes_one_json_document_and_exits_as_declared(
    base: str,
    movable: str,
    bare: str,
    runnable: str,
    forbidden: str,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verb: str,
    exit_code: int,
) -> None:
    monkeypatch.chdir(tmp_path)  # `skills` writes into the project, and under HOME with --user
    PREPARE.get((verb, exit_code), lambda: None)()
    manifest = next(v for v in _manifest(capsys) if v["verb"] == verb)
    argv = [
        a.format(
            server=base, movable=movable, bare=bare, runnable=runnable, forbidden=forbidden, down=_closed_port_url()
        )
        for a in CASES[verb, exit_code]
    ]

    code, doc = _run(capsys, argv, {"HOME": str(tmp_path / "home")})

    assert code == exit_code
    assert exit_code in manifest["exit_codes"]
    # A failed doctor check and a refused move still report their keys; any other refusal is an error document.
    reports = exit_code == 0 or (verb, exit_code) in {("doctor", 1), ("task move", 1)}
    assert set(doc) == (set(manifest["outputs"]) if reports else {"error", "code"})


SKILLS = ["operating-starpulse-board", "setting-up-starpulse"]


def test_skills_install_copies_the_bundled_skills_for_each_harness_chosen_into_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    code, doc = _run(capsys, ["skills", "install", "--claude", "--codex"], {"HOME": str(tmp_path / "home")})

    assert code == 0
    assert doc["scope"] == "project"
    assert {(i["harness"], i["skill"]) for i in doc["installed"]} == {
        (h, s) for h in ("claude", "codex") for s in SKILLS
    }
    for skill in SKILLS:
        assert (tmp_path / ".claude/skills" / skill / "SKILL.md").is_file()
        assert (tmp_path / ".agents/skills" / skill / "SKILL.md").is_file()
    assert not (tmp_path / "home").exists()


def test_skills_install_with_user_writes_under_the_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, home = tmp_path / "project", tmp_path / "home"
    project.mkdir()
    monkeypatch.chdir(project)

    code, doc = _run(capsys, ["skills", "install", "--codex", "--user"], {"HOME": str(home)})

    assert (code, doc["scope"]) == (0, "user")
    assert (home / ".agents/skills/setting-up-starpulse/SKILL.md").is_file()
    assert not (home / ".claude").exists()
    assert list(project.iterdir()) == []


def test_skills_install_without_a_harness_is_a_usage_error_naming_the_flags(capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["skills", "install"])

    assert (code, doc["code"]) == (2, "usage")
    assert "--claude" in doc["error"] and "--codex" in doc["error"]


def test_skills_install_refuses_a_modified_copy_until_forced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    _run(capsys, ["skills", "install", "--claude"])
    edited = tmp_path / ".claude/skills/operating-starpulse-board/SKILL.md"
    edited.write_text("mine\n")

    code, doc = _run(capsys, ["skills", "install", "--claude"])

    assert (code, doc["code"]) == (1, "refused")
    assert "operating-starpulse-board" in doc["error"] and "--force" in doc["error"]
    assert edited.read_text() == "mine\n"

    code, doc = _run(capsys, ["skills", "install", "--claude", "--force"])

    assert code == 0
    assert edited.read_text().startswith("---\nname: operating-starpulse-board")


def test_skills_list_reports_each_skills_status_per_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    _run(capsys, ["skills", "install", "--claude"])
    (tmp_path / ".claude/skills/setting-up-starpulse/SKILL.md").write_text("mine\n")

    code, doc = _run(capsys, ["skills", "list"])

    assert code == 0
    assert doc["scope"] == "project"
    assert [(s["name"], s["claude"], s["codex"]) for s in doc["skills"]] == [
        ("operating-starpulse-board", "installed", "absent"),
        ("setting-up-starpulse", "modified", "absent"),
    ]
    assert all(s["description"] for s in doc["skills"])


def test_skills_list_with_user_reads_the_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    environ = {"HOME": str(tmp_path / "home")}
    _run(capsys, ["skills", "install", "--codex", "--user"], environ)

    _, doc = _run(capsys, ["skills", "list", "--user"], environ)

    assert (doc["scope"], {s["codex"] for s in doc["skills"]}, {s["claude"] for s in doc["skills"]}) == (
        "user",
        {"installed"},
        {"absent"},
    )


def test_every_skill_is_a_directory_named_in_its_front_matter_with_a_description() -> None:
    assert skill_install.names() == SKILLS
    for name in SKILLS:
        text = (skill_install.SOURCE / name / "SKILL.md").read_text()
        assert f"\nname: {name}\n" in text.split("---")[1]
        assert skill_install.description(name)


def test_every_verb_and_flag_a_bundled_skill_names_is_in_the_manifest(capsys: pytest.CaptureFixture[str]) -> None:
    verbs = {v["verb"]: {f for a in v["arguments"] for f in a["flags"]} for v in _manifest(capsys)}
    named = 0
    for name in skill_install.names():
        for span in re.findall(r"`starpulse ([^`]+)`", (skill_install.SOURCE / name / "SKILL.md").read_text()):
            words = span.split()
            if words[0] in ("serve", "emit"):  # run through their own parsers, not the verb manifest
                continue
            leaf = next((" ".join(words[:n]) for n in (2, 1) if " ".join(words[:n]) in verbs), None)
            assert leaf, f"{name} names `starpulse {span}`, which is no manifest verb"
            flags = {w.split("=")[0] for w in words if w.startswith("--")}
            assert flags <= verbs[leaf], f"{name} gives `starpulse {leaf}` {flags - verbs[leaf]}"
            named += 1
    assert named >= 8  # the skills do name verbs; a regex that matched nothing would pass vacuously
