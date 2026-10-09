"""`starpulse snapshot|board|task show|help --agent`: an agent reads the running server and gets one JSON document."""

import json
import re
import shutil
import socket
import string
import threading
import time
import urllib.request
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.board import native
from starpulse._internal.board.seam import Written
from starpulse._internal.board.upstream_backlog import UpstreamBacklog
from starpulse._internal.kit.adapter_kit import serve as _real_serve
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.kit.adapter_kit import url as _url
from starpulse._internal.server.server import _no_writer
from starpulse._internal.cli import agent_cli as cli
from starpulse._internal.cli import skill_install
from starpulse.contracts.adapters import Move
from starpulse._internal.config.level import Level, Orbit, Terminal
from starpulse._internal.cli import doctor
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.eventlog.history import HistoryStore
from starpulse.tests.hosts import FakeHost
from starpulse.tests.machines import MACHINES
from starpulse.tests.unit.level.test_analytics import NOW, ROWS, H

VALID_MACHINE = Path(__file__).parent.parent.parent.parent / "machines" / "harness.yaml"
STARTED = [0]  # server lifecycles begun in this process, so a test can prove which fixtures a case builds


@contextmanager
def _serve(*args: Any, **kwargs: Any) -> Iterator[Any]:
    STARTED[0] += 1
    with _real_serve(*args, **kwargs) as server:
        yield server


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
    pull = {
        "number": 5,
        "url": PULL,
        "checks": "pass",
        "merged": False,
        "merge_sha": None,
        "merged_at": None,
        "threads": 2,
        "stale": False,
    }
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
def leveled(tmp_path: Path) -> Iterator[str]:
    """A hub's address: a level on the Board and 90 hours of history from two sources, the clock at `NOW`."""
    level = Level(
        "board",
        "done",
        (Terminal("done", "goal"),),
        gates=("review",),
        orbit=Orbit("working", ("in_progress", "review")),
    )
    store = HistoryStore(f"sqlite:///{tmp_path / 'level.sqlite'}", MACHINES)
    for i, (task_id, at, _old, new) in enumerate(ROWS):
        store.record_lane(f"{'a' if task_id in 'AB' else 'b'}/{i}", task_id, new, at)
    with _serve(tmp_path, BoardFeed(machines=MACHINES), history=store, clock=lambda: NOW, level=level) as server:
        yield _url(server, "")


@pytest.fixture
def bare(tmp_path: Path) -> Iterator[str]:
    """A server with `_moving_board` and no board writer, as one with no `[board]` adapter that writes."""
    with _serve(tmp_path, _moving_board(), writer=_no_writer) as server:
        yield _url(server, "")


@pytest.fixture
def milestoned(tmp_path: Path) -> Iterator[str]:
    """A server whose native board keeps one open milestone, `m-106`, and one open doc, `doc-84`, copied from real
    Backlog.md files."""
    board = native.board({}, tmp_path)
    source = Path(__file__).parent.parent.parent / "fixtures" / "native_board"
    for records in ("milestones", "docs"):
        shutil.copytree(source / records, tmp_path / ".starpulse" / "board" / records)
    with _serve(tmp_path, BoardFeed(machines=MACHINES), milestones=board) as server:
        yield _url(server, "")


TASK_FILE = """---
id: task-1
title: Draw the board
status: To Do
assignee:
  - '@agent-standard-high'
labels:
  - ui
priority: high
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Draw it.
<!-- SECTION:DESCRIPTION:END -->
"""


def _task_file(tmp_path: Path, task_id: str = "task-1") -> Path:
    """The file of a task of the `tasked` board, found by its id whatever its title's slug."""
    return next((tmp_path / ".starpulse" / "board" / "tasks").glob(f"{task_id} - *.md"))


@pytest.fixture
def tasked(tmp_path: Path) -> Iterator[str]:
    """A server whose native board holds `task-1`, read, edited, created and assigned through its own writers."""
    board = native.board({}, tmp_path)
    root = tmp_path / ".starpulse" / "board"
    (root / "tasks" / "task-1 - Draw the board.md").write_text(TASK_FILE)
    feed = BoardFeed(machines=MACHINES)
    UpstreamBacklog(root, feed.put).scan()
    with _serve(
        tmp_path,
        feed,
        writer=board.writer,
        assign=board.assign,
        read=board.read,
        edit=board.edit,
        create=board.create,
    ) as server:
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
        "prs": [
            {
                "number": 5,
                "url": PULL,
                "checks": "pass",
                "merged": False,
                "merge_sha": None,
                "merged_at": None,
                "threads": 2,
                "stale": False,
            }
        ],
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
        f"{movable}/api/move",
        data=json.dumps({"task": "PROJ-6", "to": "ready"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
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


def test_task_create_writes_a_task_with_the_details_given_and_reports_its_id(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["task", "create", "Rotate the secret", "--priority", "High", "--milestone", "m-3", "--assignee", "@agent-a"]
    argv += ["--description", "Rotate it.", "--label", "ops", "--label", "sec", "--dependency", "task-1"]
    argv += ["--ac", "It rotates", "--ac", "It logs", "--server", tasked]

    code, doc = _run(capsys, argv)

    assert (code, doc) == (0, {"task": "task-2"})
    written = _task_file(tmp_path, "task-2").read_text()
    assert "title: Rotate the secret" in written
    assert "priority: high" in written
    assert "milestone: m-3" in written
    assert "- '@agent-a'" in written
    assert "- ops\n- sec" in written
    assert "- task-1" in written
    assert "Rotate it." in written
    assert "- [ ] #1 It rotates\n- [ ] #2 It logs" in written


def test_task_create_with_a_priority_the_board_does_not_know_is_refused_and_writes_nothing(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "create", "Rotate", "--priority", "urgent", "--server", tasked])

    assert (code, doc["code"]) == (1, "refused")
    assert "priority" in doc["error"]
    assert not list((tmp_path / ".starpulse" / "board" / "tasks").glob("task-2 - *.md"))


def test_task_edit_writes_every_field_given_in_one_write_and_reports_those_that_changed(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["task", "edit", "task-1", "--title", "Draw the lanes", "--priority", "low", "--label", "ui", "--label", "api"]
    argv += ["--description", "Draw them.", "--comment", "Retitled", "--server", tasked]

    code, doc = _run(capsys, argv)

    assert code == 0
    assert doc["task"] == "task-1"
    assert sorted(doc["changed"]) == ["description", "labels", "priority", "title"]
    written = _task_file(tmp_path).read_text()
    assert "title: Draw the lanes" in written
    assert "priority: low" in written
    assert "- ui\n- api" in written
    assert "Draw them." in written
    assert "Retitled" in written


def test_task_edit_that_changes_nothing_writes_nothing(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _task_file(tmp_path).read_text()

    code, doc = _run(capsys, ["task", "edit", "task-1", "--priority", "high", "--server", tasked])

    assert (code, doc) == (0, {"task": "task-1", "changed": []})
    assert _task_file(tmp_path).read_text() == before


def test_task_edit_against_a_base_a_field_has_left_is_refused_whole_and_writes_nothing(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _task_file(tmp_path).read_text()
    base = json.dumps({"title": "Draw the board", "priority": "medium"})  # the priority is high on the board

    code, doc = _run(
        capsys,
        ["task", "edit", "task-1", "--title", "Draw the lanes", "--priority", "low", "--base", base, "--server", tasked],
    )

    assert (code, doc["code"]) == (1, "refused")
    assert "priority" in doc["error"]
    assert _task_file(tmp_path).read_text() == before


def test_task_edit_with_a_base_that_is_no_json_object_is_a_usage_error(
    tasked: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "edit", "task-1", "--title", "X", "--base", "[1]", "--server", tasked])

    assert (code, doc["code"]) == (2, "usage")
    assert "--base" in doc["error"]


def test_task_assign_sets_the_assignee_and_nothing_else(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "assign", "task-1", "@agent-fast-low", "--server", tasked])

    assert (code, doc) == (0, {"task": "task-1", "assignee": "@agent-fast-low", "changed": ["profile"]})
    written = _task_file(tmp_path).read_text()
    assert "- '@agent-fast-low'" in written
    assert "@agent-standard-high" not in written
    assert "title: Draw the board" in written


def test_task_edit_on_a_board_that_cannot_edit_exits_3_and_says_so(bare: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "edit", "PROJ-6", "--title", "X", "--server", bare])

    assert (code, doc["code"]) == (3, "unavailable")


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
        "task create",
        "task edit",
        "task assign",
        "machine list",
        "machine show",
        "machine validate",
        "machine import mermaid",
        "milestone list",
        "milestone show",
        "milestone add",
        "milestone edit",
        "milestone archive",
        "doc list",
        "doc show",
        "doc create",
        "doc update",
        "doc archive",
        "runs list",
        "runs start",
        "watch",
        "analytics health",
        "analytics level",
        "analytics trajectories",
        "analytics gates",
        "analytics forecast",
        "analytics what-if",
        "config check",
        "demo",
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


def test_analytics_level_serves_the_levels_flow_numbers_and_orbit_shares_as_the_server_computes_them(
    leveled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", "level", "--hours", "48", "--server", leveled])

    assert code == 0
    assert (doc["machine"], doc["goal"], doc["window_s"], doc["history_s"]) == ("board", "done", 48 * H, 90 * H)
    assert doc["wip"] == {"count": 1, "states": {"in_progress": 1}}
    assert doc["throughput"] == {"count": 2, "per_day": 1.0}
    assert doc["aging"]["threshold_s"] == 25 * H
    assert [source["id"] for source in doc["sources"]] == ["a", "b"]
    assert doc["orbit"]["terminals"] == {"done": {"ended": 2}}
    for source in doc["sources"]:
        assert sum(source["time_share"].values()) == pytest.approx(1.0)


def test_analytics_level_refuses_a_window_longer_than_the_history_naming_the_history(
    leveled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", "level", "--hours", "91", "--server", leveled])

    assert (code, doc["code"], "90 hours" in doc["error"]) == (1, "refused", True)


def test_analytics_level_of_a_server_with_no_level_is_unavailable(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", "level", "--server", base])

    assert (code, doc["code"], "[level]" in doc["error"]) == (3, "unavailable", True)


def test_analytics_trajectories_serves_variants_the_norm_outliers_the_chain_and_betweenness(
    leveled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", "trajectories", "--hours", "48", "--server", leveled])

    assert code == 0
    assert (doc["machine"], doc["goal"], doc["ended"], doc["history_s"]) == ("board", "done", 2, 90 * H)
    assert [variant["count"] for variant in doc["variants"]] == [1, 1]
    assert doc["norm"]["path"] == ["ready", "in_progress", "review", "in_progress", "done"]
    assert [(o["task"], o["distance"]) for o in doc["outliers"]] == [("A", 2)]
    assert doc["chain"]["review"]["p_goal"] == pytest.approx(1.0)
    assert set(doc["betweenness"]) == {"to_do", "ready", "in_progress", "review", "done"}
    assert doc["bottleneck"]["state"] == "in_progress"
    assert doc["loops"] == [{"from": "review", "to": "in_progress", "runs": 1, "trips": 1, "days": 16 * H / 86400}]
    assert [(run["task"], run["back_edges"], run["sccs"]) for run in doc["runs"]] == [("A", 0, 0), ("B", 1, 1)]
    assert "gates" not in doc
    assert "dominators" not in json.dumps(doc["runs"])


def test_analytics_gates_marks_a_bypassed_gate_bypassable_and_returns_the_bypassing_runs_path(
    leveled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", "gates", "--hours", "48", "--server", leveled])

    assert code == 0
    assert doc["gates"] == [
        {
            "gate": "review",
            "runs": 2,
            "crossed": 2,
            "mandatory": 1,
            "bypassed": 1,
            "bypassable": True,
            "witness": {"task": "B", "path": ["ready", "in_progress", "done"]},
        }
    ]
    by_task = {run["task"]: run["gates"][0] for run in doc["runs"]}
    assert (by_task["A"]["mandatory"], by_task["A"]["dominators"], by_task["A"]["post_dominators"]) == (
        True,
        ["to_do", "ready", "in_progress"],
        ["done"],
    )
    assert (by_task["B"]["mandatory"], by_task["B"]["witness"]) == (False, ["ready", "in_progress", "done"])


def test_analytics_gates_for_one_task_lists_only_its_trajectory(
    leveled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", "gates", "--task", "B", "--hours", "48", "--server", leveled])

    assert code == 0
    assert [run["task"] for run in doc["runs"]] == ["B"]
    assert doc["gates"][0]["bypassable"] is True  # the level's summary is the level's, not the task's


def test_analytics_gates_of_a_task_that_ended_nowhere_in_the_window_is_not_found(
    leveled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", "gates", "--task", "F", "--hours", "48", "--server", leveled])

    assert (code, doc["code"], "F" in doc["error"]) == (4, "not_found", True)


def test_analytics_forecast_for_one_task_gives_its_chances_with_the_rows_sample_size(
    leveled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", "forecast", "--task", "C", "--hours", "48", "--server", leveled])

    assert code == 0
    [forecast] = doc["forecast"]
    assert (forecast["task"], forecast["state"], forecast["n"], forecast["pooled"]) == ("C", "in_progress", 3, True)
    assert forecast["p_goal"] == pytest.approx(1.0)
    assert doc["calibration"]["held_out"] == 0
    assert "runs" not in doc


def test_analytics_forecast_of_a_task_with_no_run_still_going_is_not_found(
    leveled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", "forecast", "--task", "A", "--hours", "48", "--server", leveled])

    assert (code, doc["code"], "A" in doc["error"]) == (4, "not_found", True)


def test_analytics_what_if_returns_the_change_in_the_goal_and_the_days(
    leveled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["analytics", "what-if", "--from", "review", "--to", "in_progress", "--p", "0", "--hours", "48"]
    code, doc = _run(capsys, [*argv, "--server", leveled])

    assert code == 0
    assert (doc["from"], doc["to"], doc["was"], doc["p"]) == ("review", "in_progress", 0.5, 0.0)
    assert doc["expected_days"]["change"] < 0


def test_analytics_what_if_on_a_state_no_run_left_is_refused(leveled: str, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["analytics", "what-if", "--from", "blocked", "--to", "done", "--p", "0.5", "--hours", "48"]
    code, doc = _run(capsys, [*argv, "--server", leveled])

    assert (code, doc["code"], "blocked" in doc["error"]) == (1, "refused", True)


@pytest.mark.parametrize("verb", ["trajectories", "gates", "forecast"])
def test_the_trajectory_verbs_refuse_a_window_longer_than_the_history_naming_the_history(
    verb: str, leveled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", verb, "--hours", "91", "--server", leveled])

    assert (code, doc["code"], "90 hours" in doc["error"]) == (1, "refused", True)


@pytest.mark.parametrize("verb", ["trajectories", "gates", "forecast"])
def test_the_trajectory_verbs_of_a_server_with_no_level_are_unavailable(
    verb: str, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", verb, "--server", base])

    assert (code, doc["code"], "[level]" in doc["error"]) == (3, "unavailable", True)


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
def _canned(status: int, body: dict[str, Any], reads: dict[str, Any] | None = None) -> Iterator[str]:
    """A server that answers every POST with `status` and the JSON `body`, as one the run guards refuse, and every
    GET with `reads` (200) when given, else 501."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if reads is None:
                self.send_error(501)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(reads).encode())

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


@pytest.fixture
def readonly() -> Iterator[str]:
    """A server that reads `task-1` and refuses every write, as one does a browser outside the private network."""
    reads = {"task": "task-1", "record": {"title": "Draw the board", "profile": "@agent-standard-high"}}
    with _canned(403, {"error": "Editing a task answers only loopback and private network (RFC 1918) browsers"}, reads) as base:
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
# is a running server, `{down}` an address nothing listens on, `{valid}` a machine that compiles and `{dir}` a directory
# of `bad.yaml` (a schema error), `ok.toml`, `bad.toml` (an unknown key), `flow.mmd` and `design/` (a demo mockup).
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
    ("analytics level", 0): ["analytics", "level", "--hours", "48", "--server", "{leveled}"],
    ("analytics level", 1): ["analytics", "level", "--hours", "91", "--server", "{leveled}"],
    ("analytics level", 2): ["analytics", "level", "--hours", "soon"],
    ("analytics level", 3): ["analytics", "level", "--server", "{server}"],
    ("analytics trajectories", 0): ["analytics", "trajectories", "--hours", "48", "--server", "{leveled}"],
    ("analytics trajectories", 1): ["analytics", "trajectories", "--hours", "91", "--server", "{leveled}"],
    ("analytics trajectories", 2): ["analytics", "trajectories", "--hours", "soon"],
    ("analytics trajectories", 3): ["analytics", "trajectories", "--server", "{server}"],
    ("analytics gates", 0): ["analytics", "gates", "--hours", "48", "--server", "{leveled}"],
    ("analytics gates", 1): ["analytics", "gates", "--hours", "91", "--server", "{leveled}"],
    ("analytics gates", 2): ["analytics", "gates", "--hours", "soon"],
    ("analytics gates", 3): ["analytics", "gates", "--server", "{server}"],
    ("analytics gates", 4): ["analytics", "gates", "--task", "Z", "--hours", "48", "--server", "{leveled}"],
    ("analytics forecast", 0): ["analytics", "forecast", "--hours", "48", "--server", "{leveled}"],
    ("analytics forecast", 1): ["analytics", "forecast", "--hours", "91", "--server", "{leveled}"],
    ("analytics forecast", 2): ["analytics", "forecast", "--hours", "soon"],
    ("analytics forecast", 3): ["analytics", "forecast", "--server", "{server}"],
    ("analytics forecast", 4): ["analytics", "forecast", "--task", "Z", "--hours", "48", "--server", "{leveled}"],
    ("analytics what-if", 0): [
        *("analytics", "what-if", "--from", "review", "--to", "in_progress", "--p", "0"),
        *("--hours", "48", "--server", "{leveled}"),
    ],
    ("analytics what-if", 1): [
        *("analytics", "what-if", "--from", "blocked", "--to", "done", "--p", "0.5"),
        *("--hours", "48", "--server", "{leveled}"),
    ],
    ("analytics what-if", 2): ["analytics", "what-if", "--from", "review", "--to", "done", "--p", "half"],
    ("analytics what-if", 3): [
        *("analytics", "what-if", "--from", "review", "--to", "done", "--p", "0.5", "--server", "{server}"),
    ],
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
    ("task create", 0): ["task", "create", "Rotate the secret", "--server", "{tasked}"],
    ("task create", 1): ["task", "create", " ", "--server", "{tasked}"],
    ("task create", 2): ["task", "create"],
    ("task create", 3): ["task", "create", "Rotate the secret", "--server", "{down}"],
    ("task edit", 0): ["task", "edit", "task-1", "--title", "Draw the lanes", "--server", "{tasked}"],
    ("task edit", 1): ["task", "edit", "task-1", "--title", " ", "--server", "{tasked}"],
    ("task edit", 2): ["task", "edit", "task-1", "--server", "{tasked}"],
    ("task edit", 3): ["task", "edit", "task-1", "--title", "Draw the lanes", "--server", "{down}"],
    ("task edit", 4): ["task", "edit", "task-99", "--title", "Draw the lanes", "--server", "{tasked}"],
    ("task assign", 0): ["task", "assign", "task-1", "@agent-fast-low", "--server", "{tasked}"],
    ("task assign", 1): ["task", "assign", "task-1", "@agent-fast-low", "--server", "{readonly}"],
    ("task assign", 2): ["task", "assign", "task-1"],
    ("task assign", 3): ["task", "assign", "task-1", "@agent-fast-low", "--server", "{down}"],
    ("task assign", 4): ["task", "assign", "task-99", "@agent-fast-low", "--server", "{tasked}"],
    ("machine list", 0): ["machine", "list", "--server", "{server}"],
    ("machine list", 2): ["machine", "list", "--nope"],
    ("machine list", 3): ["machine", "list", "--server", "{down}"],
    ("machine show", 0): ["machine", "show", "board", "--server", "{server}"],
    ("machine show", 2): ["machine", "show"],
    ("machine show", 3): ["machine", "show", "board", "--server", "{down}"],
    ("machine show", 4): ["machine", "show", "nowhere", "--server", "{server}"],
    ("milestone list", 0): ["milestone", "list", "--server", "{milestoned}"],
    ("milestone list", 2): ["milestone", "list", "--nope"],
    ("milestone list", 3): ["milestone", "list", "--server", "{server}"],  # a board that keeps no milestones
    ("milestone show", 0): ["milestone", "show", "m-106", "--server", "{milestoned}"],
    ("milestone show", 2): ["milestone", "show"],
    ("milestone show", 3): ["milestone", "show", "m-106", "--server", "{down}"],
    ("milestone show", 4): ["milestone", "show", "m-99", "--server", "{milestoned}"],
    ("milestone add", 0): ["milestone", "add", "Launch", "--outcome", "Shipped", "--server", "{milestoned}"],
    ("milestone add", 1): ["milestone", "add", " ", "--server", "{milestoned}"],
    ("milestone add", 2): ["milestone", "add"],
    ("milestone add", 3): ["milestone", "add", "Launch", "--server", "{down}"],
    ("milestone edit", 0): ["milestone", "edit", "m-106", "--outcome", "Shipped", "--server", "{milestoned}"],
    ("milestone edit", 1): ["milestone", "edit", "m-106", "--title", " ", "--server", "{milestoned}"],
    ("milestone edit", 2): ["milestone", "edit", "m-106", "--server", "{milestoned}"],
    ("milestone edit", 3): ["milestone", "edit", "m-106", "--outcome", "Shipped", "--server", "{down}"],
    ("milestone edit", 4): ["milestone", "edit", "m-99", "--outcome", "Shipped", "--server", "{milestoned}"],
    ("milestone archive", 0): ["milestone", "archive", "m-106", "--server", "{milestoned}"],
    ("milestone archive", 1): ["milestone", "archive", "m-106", "--server", "{forbidden}"],
    ("milestone archive", 2): ["milestone", "archive"],
    ("milestone archive", 3): ["milestone", "archive", "m-106", "--server", "{down}"],
    ("milestone archive", 4): ["milestone", "archive", "m-99", "--server", "{milestoned}"],
    ("doc list", 0): ["doc", "list", "--server", "{milestoned}"],
    ("doc list", 2): ["doc", "list", "--nope"],
    ("doc list", 3): ["doc", "list", "--server", "{server}"],  # a board that keeps no docs
    ("doc show", 0): ["doc", "show", "doc-84", "--server", "{milestoned}"],
    ("doc show", 2): ["doc", "show"],
    ("doc show", 3): ["doc", "show", "doc-84", "--server", "{down}"],
    ("doc show", 4): ["doc", "show", "doc-99", "--server", "{milestoned}"],
    ("doc create", 0): ["doc", "create", "Plan", "--type", "guide", "--body", "Hi", "--server", "{milestoned}"],
    ("doc create", 1): ["doc", "create", " ", "--server", "{milestoned}"],
    ("doc create", 2): ["doc", "create"],
    ("doc create", 3): ["doc", "create", "Plan", "--server", "{down}"],
    ("doc update", 0): ["doc", "update", "doc-84", "--body", "Report", "--server", "{milestoned}"],
    ("doc update", 1): ["doc", "update", "doc-84", "--title", " ", "--server", "{milestoned}"],
    ("doc update", 2): ["doc", "update", "doc-84", "--server", "{milestoned}"],
    ("doc update", 3): ["doc", "update", "doc-84", "--body", "Report", "--server", "{down}"],
    ("doc update", 4): ["doc", "update", "doc-99", "--body", "Report", "--server", "{milestoned}"],
    ("doc archive", 0): ["doc", "archive", "doc-84", "--server", "{milestoned}"],
    ("doc archive", 1): ["doc", "archive", "doc-84", "--server", "{forbidden}"],
    ("doc archive", 2): ["doc", "archive"],
    ("doc archive", 3): ["doc", "archive", "doc-84", "--server", "{down}"],
    ("doc archive", 4): ["doc", "archive", "doc-99", "--server", "{milestoned}"],
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
    ("machine validate", 0): ["machine", "validate", "{valid}"],
    ("machine validate", 1): ["machine", "validate", "{dir}/bad.yaml"],
    ("machine validate", 2): ["machine", "validate"],
    ("machine import mermaid", 0): ["machine", "import", "mermaid", "{dir}/flow.mmd", "--out", "{dir}/flow.yaml"],
    ("machine import mermaid", 1): ["machine", "import", "mermaid", "{dir}/flow.mmd", "--out", "{dir}/bad.yaml"],
    ("machine import mermaid", 2): ["machine", "import", "mermaid"],
    ("machine import mermaid", 4): ["machine", "import", "mermaid", "{dir}/nope.mmd"],
    ("config check", 0): ["config", "check", "--config", "{dir}/ok.toml"],
    ("config check", 1): ["config", "check", "--config", "{dir}/bad.toml"],
    ("config check", 2): ["config", "check", "--nope"],
    ("demo", 0): ["demo", "--mockup", "{dir}/design", "--out", "{dir}/demo.html"],
    ("demo", 1): ["demo", "--mockup", "{dir}/nope", "--out", "{dir}/demo.html"],
    ("demo", 2): ["demo"],
    ("demo", 3): ["demo", "--server", "{down}", "--out", "{dir}/demo.html"],
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


def _case_files(root: Path) -> Path:
    """The files the offline verbs' cases name, in a fresh directory."""
    (root / "design").mkdir(parents=True)
    (root / "bad.yaml").write_text("name: flow\nstates:\n  idle: {initial: true}\n  done: {final: maybe}\nevents: {}\n")
    (root / "ok.toml").write_text('tracker_url = "http://tracker.example"\n')
    (root / "bad.toml").write_text('colour = "red"\n')
    (root / "flow.mmd").write_text("stateDiagram-v2\n    [*] --> open\n    open --> closed : Close it\n")
    board = {"agents": [{"id": "PROJ-1", "title": "Rotate the secret", "state": "ready"}]}
    snap = {"now": 1.0, "dags": [], "flows": {"board": board, "in-progress": {"agents": []}}}
    (root / "design" / "data.js").write_text(f"window.SNAP = {json.dumps(snap)};\n")
    (root / "design" / "index.html").write_text('<script src="data.js"></script>')
    return root


SERVERS = {
    "server": "base",
    "leveled": "leveled",
    "movable": "movable",
    "bare": "bare",
    "runnable": "runnable",
    "forbidden": "forbidden",
    "milestoned": "milestoned",
    "tasked": "tasked",
    "readonly": "readonly",
}


def _servers(request: pytest.FixtureRequest, template: Sequence[str]) -> dict[str, str]:
    """The servers a template names, each built only if named: a case never pays for a server it does not use."""
    named = {name for arg in template for _, name, _, _ in string.Formatter().parse(arg)}
    return {name: request.getfixturevalue(fixture) for name, fixture in SERVERS.items() if name in named}


def test_a_manifest_case_builds_only_the_servers_its_template_names(request: pytest.FixtureRequest) -> None:
    for template, built in ((["task", "move", "PROJ-6", "review", "--server", "{bare}"], 1), (["skills", "list"], 0)):
        before = STARTED[0]

        _servers(request, template)

        assert STARTED[0] - before == built


@pytest.mark.parametrize(("verb", "exit_code"), list(CASES))
def test_a_manifest_verb_writes_one_json_document_and_exits_as_declared(
    request: pytest.FixtureRequest,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verb: str,
    exit_code: int,
) -> None:
    monkeypatch.chdir(tmp_path)  # `skills` writes into the project, and under HOME with --user
    PREPARE.get((verb, exit_code), lambda: None)()
    manifest = next(v for v in _manifest(capsys) if v["verb"] == verb)
    files = _case_files(tmp_path / "cases")
    template = CASES[verb, exit_code]
    servers = _servers(request, template)
    argv = [a.format(**servers, down=_closed_port_url(), valid=VALID_MACHINE, dir=files) for a in template]

    code, doc = _run(capsys, argv, {"HOME": str(tmp_path / "home")})

    assert code == exit_code
    assert exit_code in manifest["exit_codes"]
    # A verb that reports `ok` still reports every check it made when it fails; any other refusal is an error document.
    reports = exit_code == 0 or (exit_code == 1 and "ok" in manifest["outputs"])
    assert set(doc) == (set(manifest["outputs"]) if reports else {"error", "code"})


SKILLS = [
    "authoring-starpulse-machines",
    "operating-starpulse-board",
    "setting-up-starpulse",
    "writing-starpulse-adapters",
]


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
        ("authoring-starpulse-machines", "installed", "absent"),
        ("operating-starpulse-board", "installed", "absent"),
        ("setting-up-starpulse", "modified", "absent"),
        ("writing-starpulse-adapters", "installed", "absent"),
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


def _named_verbs(skill: str, verbs: dict[str, set[str]]) -> list[str]:
    """The manifest verb behind each `starpulse ...` command the skill names, each with its flags checked."""
    named = []
    for span in re.findall(r"`starpulse ([^`]+)`", (skill_install.SOURCE / skill / "SKILL.md").read_text()):
        words = span.split()
        if words[0] in ("serve", "emit"):  # run through their own parsers, not the verb manifest
            continue
        leaf = next((" ".join(words[:n]) for n in (3, 2, 1) if " ".join(words[:n]) in verbs), None)
        assert leaf, f"{skill} names `starpulse {span}`, which is no manifest verb"
        flags = {w.split("=")[0] for w in words if w.startswith("--")}
        assert flags <= verbs[leaf], f"{skill} gives `starpulse {leaf}` {flags - verbs[leaf]}"
        named.append(leaf)
    return named


def test_every_verb_and_flag_a_bundled_skill_names_is_in_the_manifest(capsys: pytest.CaptureFixture[str]) -> None:
    verbs = {v["verb"]: {f for a in v["arguments"] for f in a["flags"]} for v in _manifest(capsys)}
    named = {skill: _named_verbs(skill, verbs) for skill in skill_install.names()}
    assert (
        sum(map(len, named.values())) >= 8
    )  # the skills do name verbs; a regex that matched nothing would pass vacuously
    assert {"machine validate", "machine import mermaid"} <= set(named["authoring-starpulse-machines"])
    assert {"doctor", "config check"} <= set(named["writing-starpulse-adapters"])
