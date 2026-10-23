"""`starpulse snapshot|board|task show|help --agent`: an agent reads the running server and gets one JSON document."""

import json
import re
import shutil
import socket
import string
import threading
import time
import urllib.request
from datetime import datetime
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine

from starpulse._internal.board import native
from starpulse._internal.board.seam import Written
from starpulse._internal.board.upstream_backlog import UpstreamBacklog
from starpulse._internal.kit.adapter_kit import serve as _real_serve
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.kit.adapter_kit import url as _url
from starpulse._internal.server.write_routes import _no_writer
from starpulse._internal.board.view import task_view
from starpulse._internal.cli import agent_cli as cli
from starpulse._internal.cli import agent_wire, skill_install
from starpulse.contracts.adapters import Move
from starpulse.tests.unit.board.test_native_lifecycle import PULL, REVIEW_NEEDS_PR, _lifecycle
from starpulse._internal.cli import doctor
from starpulse._internal.feed.board_feed import HOT_S, BoardFeed
from starpulse._internal.feed.search import SearchIndex
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import HistoryStore
from starpulse._internal.harnesses.telemetry import TelemetryLog, signals
from starpulse.contracts.adapters import TaskKeys
from starpulse.tests.fake_board import bare_board
from starpulse.tests.hosts import FakeHost
from starpulse.tests.machines import MACHINES, ROLES
from starpulse.tests.unit.harnesses.test_telemetry import FIXTURES

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
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(
        task(
            "PROJ-1",
            "To Do",
            milestone="m-1",
            labels=("cli",),
            profile="@agent-a",
            dependencies=("PROJ-2", "PROJ-3"),
            references=(PULL, "docs/plan.md"),
            description="Add the verbs, as in `TASK-9` and TASK-9.",
            moves={
                "in_progress": Move(allowed=False, reason="claim it first", skill="starting-tasks"),
                "ready": Move(allowed=True),
            },
        )
    )
    feed.put(
        task(
            "PROJ-2",
            "Ready",
            milestone="m-2",
            labels=("api", "cli"),
            profile="@agent-b",
            references=(UNREAD_PULL,),
            type="spike",
        )
    )
    feed.put(task("PROJ-3", "Done", settled="completed"))
    feed.put(
        task(
            "PROJ-4",
            "In Progress",
            milestone="m-2",
            labels=("api",),
            profile="@agent-a",
            assignee="session-1",
            type="story",
            acceptance_criteria=("first", "second", "third", "fourth"),
            acceptance_checked=(True, True, False, False),
            pause_reason="Restart the server",
        )
    )
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
    store.record_machine(
        "r0-0", {"event_id": "r0", "machine": "in-progress", "event": "WORKTREE_READY", "run": "run-9", "time": 300.0}
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
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
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


COLD_RECORDS = {
    "PROJ-1": {"title": "Cold one", "profile": "agent", "labels": ["a"], "milestone": "m-1", "type": "story"},
    "PROJ-2": {"title": "Cold two", "profile": "agent", "labels": [], "milestone": "m-2", "type": "story"},
    "PROJ-3": {"title": "Cold three", "profile": "agent", "labels": [], "milestone": "m-1", "type": "story"},
}


@pytest.fixture
def cooled(tmp_path: Path) -> Iterator[str]:
    """A server whose board holds three done tasks past their hot day (two in `m-1`) and one hot done task in `m-1`."""
    now = 10_000_000.0
    feed = BoardFeed(roles=ROLES, machines=MACHINES, clock=lambda: now)
    feed.expect("0-0")
    for n in (1, 2, 3):
        feed.put(task(f"PROJ-{n}", "Done", observed_at=now - 2 * HOT_S - n))
    feed.put(task("PROJ-4", "Done", observed_at=now - 60, milestone="m-1"))
    with _serve(tmp_path, feed, bare_board(read=COLD_RECORDS.get)) as server:
        yield _url(server, "")


@pytest.fixture
def movable(tmp_path: Path, writer: _Writer) -> Iterator[str]:
    """A server whose board writer answers, holding `_moving_board`."""
    with _serve(tmp_path, _moving_board(), bare_board(writer=writer)) as server:
        yield _url(server, "")


#: An hour after the recorded Claude Code export the `stepped` server holds.
STEPS_NOW = datetime.fromisoformat("2026-10-09T22:30:00+00:00").timestamp()


@pytest.fixture
def stepped(tmp_path: Path) -> Iterator[str]:
    """A server that received one recorded Claude Code export of three model requests, the clock an hour after it."""
    keys = TaskKeys(
        key=re.compile(r"TASK-\d+"),
        branch=re.compile(r"(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", re.IGNORECASE),
        key_format="TASK-{}",
    )
    telemetry = TelemetryLog(EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))
    for line in (FIXTURES / "claude_code" / "otlp.ndjson").read_text().splitlines():
        telemetry.publish(signals(json.loads(line)))
    with _serve(
        tmp_path, BoardFeed(roles=ROLES, machines=MACHINES, keys=keys), telemetry=telemetry, clock=lambda: STEPS_NOW
    ) as server:
        yield _url(server, "")


@pytest.fixture
def bare(tmp_path: Path) -> Iterator[str]:
    """A server with `_moving_board` and no board writer, as one with no `[board]` adapter that writes."""
    with _serve(tmp_path, _moving_board(), bare_board(writer=_no_writer)) as server:
        yield _url(server, "")


@pytest.fixture
def milestoned(tmp_path: Path) -> Iterator[str]:
    """A server whose native board keeps one open milestone, `m-106`, and one open doc, `doc-84`, copied from real
    Backlog.md files."""
    board = native.board({}, tmp_path)
    source = Path(__file__).parent.parent.parent / "fixtures" / "native_board"
    for records in ("milestones", "docs"):
        shutil.copytree(source / records, tmp_path / ".starpulse" / "board" / records)
    with _serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), board) as server:
        yield _url(server, "")


TASK_FILE = """---
id: task-1
title: Draw the board
status: To Do
profile:
  - '@agent-standard-high'
labels:
  - ui
priority: high
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Draw it.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria

<!-- AC:BEGIN -->
- [ ] #1 It draws
- [ ] #2 It scales
<!-- AC:END -->
"""

CHECKED_FILE = TASK_FILE.replace(
    "Draw it.\n",
    "Draw it.\n\n## Post-merge Checks\n\n```yaml\npost_merge_checks:\n"
    "  - {id: live, text: It draws, within: 1d, pass: {kind: prom, expr: up}}\n```\n",
)

SHIPPED_FILE = """---
id: task-2
title: Ship the board
status: Done
---
"""


def _task_file(tmp_path: Path, task_id: str = "task-1") -> Path:
    """The file of a task of the `tasked` board, found by its id whatever its title's slug."""
    return next((tmp_path / ".starpulse" / "board" / "tasks").glob(f"{task_id} - *.md"))


@contextmanager
def _native_server(tmp_path: Path, *files: tuple[str, str]) -> Iterator[str]:
    """A server whose native board holds `task-1` and each `(name, text)` file, written through its own writers."""
    board = native.board({}, tmp_path)
    root = tmp_path / ".starpulse" / "board"
    for name, text in (("task-1 - Draw the board.md", TASK_FILE), *files):
        (root / "tasks" / name).write_text(text)
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    UpstreamBacklog(root, feed.put).scan()
    with _serve(tmp_path, feed, board) as server:
        yield _url(server, "")


@pytest.fixture
def tasked(tmp_path: Path) -> Iterator[str]:
    """A server whose native board holds `task-1`, read, edited, created, assigned, archived and completed through its
    own writers."""
    with _native_server(tmp_path) as url:
        yield url


@pytest.fixture
def lifecycled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A server whose native board has the lifecycle lanes and a rule that Review needs a pull request: `task-1` is
    Ready, `task-2` In Progress and `task-3` Done."""
    tasks = {"task-1": ("Ready", {}), "task-2": ("In Progress", {}), "task-3": ("Done", {})}
    feed, built = _lifecycle(tmp_path, monkeypatch, tasks, [REVIEW_NEEDS_PR])
    with _serve(tmp_path, feed, bare_board(writer=built.writer, read=built.read, edit=built.edit)) as server:
        yield _url(server, "")


@pytest.fixture
def checked(tmp_path: Path) -> Iterator[str]:
    """The `tasked` server whose `task-1` declares the post-merge check `live`."""
    with _native_server(tmp_path, ("task-1 - Draw the board.md", CHECKED_FILE)) as url:
        yield url


@pytest.fixture
def archived(tmp_path: Path) -> Iterator[str]:
    """The `tasked` server with `task-1` moved into the board's archive."""
    with _native_server(tmp_path) as url:
        file = _task_file(tmp_path)
        (tmp_path / ".starpulse" / "board" / "archive" / "tasks").mkdir(parents=True)
        file.replace(tmp_path / ".starpulse" / "board" / "archive" / "tasks" / file.name)
        yield url


@pytest.fixture
def shelved(tmp_path: Path) -> Iterator[str]:
    """The `milestoned` server with `doc-84` moved into the board's archive."""
    board = native.board({}, tmp_path)
    source = Path(__file__).parent.parent.parent / "fixtures" / "native_board"
    root = tmp_path / ".starpulse" / "board"
    for records in ("milestones", "docs"):
        shutil.copytree(source / records, root / records)
    (root / "archive" / "docs").mkdir(parents=True)
    file = next((root / "docs").rglob("doc-84 - *.md"))
    file.replace(root / "archive" / "docs" / file.name)
    with _serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), board) as server:
        yield _url(server, "")


@pytest.fixture
def shipped(tmp_path: Path) -> Iterator[str]:
    """The `tasked` server with a Done `task-2` as well."""
    with _native_server(tmp_path, ("task-2 - Ship the board.md", SHIPPED_FILE)) as url:
        yield url


@pytest.fixture
def retiring(tmp_path: Path) -> Iterator[str]:
    """A server whose native board, started on a history store, holds `task-1` and a Done `task-2`, retired, read back,
    imported and restored through its own writers. The single scan replaces the poll only while the board starts: this
    server is shared for the module, and a patch held that long reaches a test of another module on the same worker."""
    board = native.board({}, tmp_path)
    root = tmp_path / ".starpulse" / "board"
    for name, text in (("task-1 - Draw the board.md", TASK_FILE), ("task-2 - Ship the board.md", SHIPPED_FILE)):
        (root / "tasks" / name).write_text(text)
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    board.start(feed, "test", EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"))
    with _serve(tmp_path, feed, board) as server:
        yield _url(server, "")


@pytest.fixture
def searchable(tmp_path: Path) -> Iterator[str]:
    """A server whose search index holds two tasks, one of them found by `signing`."""
    index = SearchIndex.open(create_engine(f"sqlite:///{tmp_path / 'search.sqlite'}"))
    assert index is not None
    index.index(task("PROJ-1", "To Do", title="Rotate the signing keys", description="Cycle the authority"))
    index.index(task("PROJ-2", "Ready", title="Drain the queue"))
    with _serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), search=index) as server:
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
        threading.Thread(target=other.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
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
    assert agent_wire.server_url(flag, env) == expected


@pytest.mark.parametrize("argv", [["snapshot"], ["board"], ["task", "show", "PROJ-1"]])
def test_a_verb_without_a_server_flag_reads_the_server_the_environment_names(
    base: str, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    code, _ = _run(capsys, argv, {"STARPULSE_URL": base})

    assert code == 0


def test_the_snapshot_verb_prints_the_servers_snapshot(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["snapshot", "--server", base])
    with urllib.request.urlopen(f"{base}/api/snapshot?view=full", timeout=5) as resp:
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
        "phase": None,
        "substate": None,
        "done_at": None,
        "profile": "@agent-a",
        "assignee": "",
        "milestone": "m-1",
        "type": "",
        "labels": ["cli"],
        "dependencies": ["PROJ-2", "PROJ-3"],
        "waiting_on": ["PROJ-2"],
        "criteria": [],
        "pause_reason": "",
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
        (["--profile", "@agent-a"], ["PROJ-1", "PROJ-4"]),
        (["--assignee", "@agent-a"], ["PROJ-1", "PROJ-4"]),  # the legacy `--assignee` named the profile
        (["--milestone", "m-2", "--label", "api", "--profile", "@agent-a"], ["PROJ-4"]),
        (["--assignee", "session-1"], ["PROJ-4"]),
        (["--assignee", "session-2"], []),
        (["--profile", "@agent-a", "--assignee", "session-1"], ["PROJ-4"]),
        (["--milestone", "m-9"], []),
        (["--type", "spike"], ["PROJ-2"]),
        (["--type", "story", "--state", "in_progress"], ["PROJ-4"]),
        (["--type", "bug"], []),
    ],
)
def test_the_board_keeps_only_the_tasks_every_filter_matches(
    base: str, capsys: pytest.CaptureFixture[str], filters: list[str], expected: list[str]
) -> None:
    code, doc = _run(capsys, ["board", *filters, "--server", base])

    assert code == 0
    assert [t["id"] for c in doc["columns"] for t in c["tasks"]] == expected


def test_each_task_names_the_session_holding_it(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    _, doc = _run(capsys, ["board", "--server", base])

    held = {t["id"]: t["assignee"] for c in doc["columns"] for t in c["tasks"]}
    assert held == {"PROJ-1": "", "PROJ-2": "", "PROJ-4": "session-1", "PROJ-5": ""}


def test_each_task_prints_its_criteria_with_their_checked_state_and_its_pause_reason(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["board", "--assignee", "session-1", "--server", base])

    assert code == 0
    [task] = [t for c in doc["columns"] for t in c["tasks"]]
    assert task["criteria"] == [
        {"text": "first", "checked": True},
        {"text": "second", "checked": True},
        {"text": "third", "checked": False},
        {"text": "fourth", "checked": False},
    ]
    assert task["pause_reason"] == "Restart the server"


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
    assert doc["description"] == f"Add the verbs, as in `TASK-9` and [TASK-9]({base}/?view=kanban&task=TASK-9)."
    assert doc["dependencies"] == ["PROJ-2", "PROJ-3"]
    assert doc["waiting_on"] == ["PROJ-2"]  # PROJ-3 is completed
    assert doc["prs"][0]["threads"] == 2
    assert doc["moves"]["in_progress"] == {"allowed": False, "reason": "claim it first", "skill": "starting-tasks"}


def test_waiting_on_drops_a_dependency_in_the_done_lane_and_keeps_one_in_progress() -> None:
    """A board that keeps Done tasks open in its `done` lane settles them there, not in `settled`."""

    def agent(task_id: str, state: str, dependencies: list[str]) -> dict[str, Any]:
        return {
            "id": task_id,
            "title": "",
            "state": state,
            "model": "",
            "milestone": "",
            "labels": [],
            "dependencies": dependencies,
            "prs": [],
            "moves": {},
        }

    board = [
        agent("PROJ-1", "waiting", ["PROJ-2", "PROJ-3"]),
        agent("PROJ-2", "done", []),
        agent("PROJ-3", "in_progress", []),
    ]
    snapshot = {"pulls": {}, "settled": {}, "roles": ROLES.wire(), "flows": [{"name": "board", "agents": board}]}

    assert task_view(board[0], snapshot)["waiting_on"] == ["PROJ-3"]


def test_task_show_reports_a_settled_task_by_where_it_settled(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "show", "PROJ-3", "--server", base])

    assert code == 0
    assert doc == {
        "id": "PROJ-3",
        "title": "",
        "lane": "completed",
        "phase": None,
        "substate": None,
        "done_at": None,
        "profile": "",
        "assignee": "",
        "milestone": "",
        "type": "",
        "labels": [],
        "dependencies": [],
        "waiting_on": [],
        "criteria": [],
        "pause_reason": "",
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
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
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
        data=json.dumps({"task": "PROJ-6", "to": "ready", "actor": "operator"}).encode(),
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
    argv = ["task", "create", "Rotate the secret", "--priority", "High", "--milestone", "m-3", "--profile", "@agent-a"]
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


def test_task_create_and_edit_write_the_impact_and_urgency(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "create", "Rank it", "--impact", "high", "--urgency", "low", "--server", tasked])
    assert (code, doc) == (0, {"task": "task-2"})
    written = _task_file(tmp_path, "task-2").read_text()
    assert "impact: high" in written and "urgency: low" in written

    code, doc = _run(capsys, ["task", "edit", "task-1", "--impact", "low", "--urgency", "high", "--server", tasked])
    assert (code, doc["changed"]) == (0, ["impact", "urgency"])
    edited = _task_file(tmp_path).read_text()
    assert "impact: low" in edited and "urgency: high" in edited


def test_task_create_with_an_impact_the_matrix_does_not_know_is_refused_and_writes_nothing(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "create", "Rank it", "--impact", "huge", "--server", tasked])

    assert (code, doc["code"]) == (1, "refused")
    assert not list((tmp_path / ".starpulse" / "board" / "tasks").glob("task-2 - *.md"))


def test_task_create_still_reads_assignee_as_the_profile(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "create", "Rotate", "--assignee", "@agent-a", "--server", tasked])

    assert (code, doc) == (0, {"task": "task-2"})
    assert "- '@agent-a'" in _task_file(tmp_path, "task-2").read_text()


def test_task_create_takes_the_status_type_references_and_definition_of_done_in_the_one_write(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["task", "create", "Rotate", "--status", "In Progress", "--type", "bug", "--reference", "docs/a.md"]
    argv += ["--documentation", "docs/b.md", "--dod", "Gates pass", "--dod", "PR is green", "--server", tasked]

    code, doc = _run(capsys, argv)

    assert (code, doc) == (0, {"task": "task-2"})
    written = _task_file(tmp_path, "task-2").read_text()
    assert "status: In Progress" in written
    assert "type: bug" in written
    assert "- docs/a.md" in written and "- docs/b.md" in written
    assert "- [ ] #1 Gates pass\n- [ ] #2 PR is green" in written


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
    argv = [
        "task",
        "edit",
        "task-1",
        "--title",
        "Draw the lanes",
        "--priority",
        "low",
        "--label",
        "ui",
        "--label",
        "api",
    ]
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
        [
            "task",
            "edit",
            "task-1",
            "--title",
            "Draw the lanes",
            "--priority",
            "low",
            "--base",
            base,
            "--server",
            tasked,
        ],
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


def test_task_profile_sets_the_profile_and_nothing_else(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "profile", "task-1", "@agent-fast-low", "--server", tasked])

    assert (code, doc) == (0, {"task": "task-1", "profile": "@agent-fast-low", "changed": ["profile"]})
    written = _task_file(tmp_path).read_text()
    assert "- '@agent-fast-low'" in written
    assert "@agent-standard-high" not in written
    assert "title: Draw the board" in written


def test_task_edit_on_a_board_that_cannot_edit_exits_3_and_says_so(
    bare: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "edit", "PROJ-6", "--title", "X", "--server", bare])

    assert (code, doc["code"]) == (3, "unavailable")


def test_task_archive_moves_the_task_out_of_its_lane_and_records_the_reason(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "archive", "task-1", "--reason", "superseded", "--server", tasked])

    assert (code, doc) == (0, {"task": "task-1"})
    board = tmp_path / ".starpulse" / "board"
    assert not list((board / "tasks").glob("task-1 - *.md"))
    assert "Archived: superseded" in next((board / "archive" / "tasks").glob("task-1 - *.md")).read_text()


def test_task_archive_without_a_reason_records_none(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "archive", "task-1", "--server", tasked])

    assert (code, doc) == (0, {"task": "task-1"})
    archived = next((tmp_path / ".starpulse" / "board" / "archive" / "tasks").glob("task-1 - *.md"))
    assert "Archived:" not in archived.read_text()


def test_task_restore_returns_the_archived_file_to_the_tasks_unchanged(
    archived: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "restore", "task-1", "--server", archived])

    assert (code, doc) == (0, {"task": "task-1"})
    board = tmp_path / ".starpulse" / "board"
    assert _task_file(tmp_path).read_text() == TASK_FILE
    assert not list((board / "archive" / "tasks").glob("task-1 - *.md"))


def test_task_restore_of_an_open_task_is_refused_and_leaves_its_file(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "restore", "task-1", "--server", tasked])

    assert (code, doc["code"]) == (1, "refused")
    assert "task-1 is already on the board" in doc["error"]
    assert _task_file(tmp_path).read_text() == TASK_FILE


def test_task_restore_undoes_an_archive_and_a_second_restore_is_refused(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gone = _run(capsys, ["task", "archive", "task-1", "--server", tasked])
    back = _run(capsys, ["task", "restore", "task-1", "--server", tasked])
    again = _run(capsys, ["task", "restore", "task-1", "--server", tasked])

    assert (gone, back) == ((0, {"task": "task-1"}), (0, {"task": "task-1"}))
    assert (again[0], again[1]["code"]) == (1, "refused")
    assert _task_file(tmp_path).is_file()


def test_task_retire_keeps_a_done_task_byte_for_byte_and_task_restore_returns_it(
    retiring: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gone = _run(capsys, ["task", "retire", "task-2", "--server", retiring])
    kept = _run(capsys, ["task", "retired", "task-2", "--server", retiring])
    off_board = list((tmp_path / ".starpulse" / "board").glob("**/task-2 - *.md"))
    back = _run(capsys, ["task", "restore", "task-2", "--server", retiring])

    assert gone == (0, {"task": "task-2"})
    assert kept == (0, {"tasks": [{"task": "task-2", "name": "task-2 - Ship the board.md", "text": SHIPPED_FILE}]})
    assert off_board == []
    assert back == (0, {"task": "task-2"})
    assert _task_file(tmp_path, "task-2").read_text() == SHIPPED_FILE
    assert _run(capsys, ["task", "retired", "--server", retiring]) == (0, {"tasks": []})


def test_task_retire_of_an_open_task_is_refused_and_leaves_its_file(
    retiring: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "retire", "task-1", "--server", retiring])

    assert (code, doc["code"]) == (1, "refused")
    assert _task_file(tmp_path).read_text() == TASK_FILE


def test_task_import_retired_keeps_each_file_and_accepts_the_same_files_again(
    retiring: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    held = tmp_path / "held"
    held.mkdir()
    old = "---\r\nid: task-3\r\ntitle: Old\r\nstatus: Done\r\n---\r\n"
    (held / "task-3 - Old.md").write_bytes(old.encode())
    (held / "task-4 - Older.md").write_text("---\nid: task-4\nstatus: Done\n---\n")
    files = [str(held / "task-3 - Old.md"), str(held / "task-4 - Older.md")]

    first = _run(capsys, ["task", "import-retired", *files, "--server", retiring])
    again = _run(capsys, ["task", "import-retired", *files, "--server", retiring])
    kept = _run(capsys, ["task", "retired", "task-3", "--server", retiring])[1]["tasks"]

    assert first == again == (0, {"tasks": ["task-3", "task-4"]})
    assert [row["text"] for row in kept] == [old]


def test_task_import_retired_of_a_file_that_is_not_there_is_a_usage_error_and_sends_nothing(
    retiring: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "task-3.md").write_text("---\nid: task-3\nstatus: Done\n---\n")
    code, doc = _run(
        capsys, ["task", "import-retired", str(tmp_path / "task-3.md"), str(tmp_path / "nope.md"), "--server", retiring]
    )

    assert (code, doc["code"]) == (2, "usage")
    assert _run(capsys, ["task", "retired", "--server", retiring]) == (0, {"tasks": []})


def test_doc_restore_returns_the_archived_file_unchanged_to_the_folder_named(
    shelved: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / ".starpulse" / "board"
    held = next((root / "archive" / "docs").glob("doc-84 - *.md"))
    text = held.read_bytes()

    code, doc = _run(capsys, ["doc", "restore", "doc-84", "--folder", "specs", "--server", shelved])

    assert (code, doc) == (0, {"doc": "doc-84"})
    assert (root / "docs" / "specs" / held.name).read_bytes() == text
    assert not held.exists()


def test_task_complete_moves_a_done_task_to_the_completed_tasks(
    shipped: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "complete", "task-2", "--server", shipped])

    assert (code, doc) == (0, {"task": "task-2"})
    board = tmp_path / ".starpulse" / "board"
    assert not list((board / "tasks").glob("task-2 - *.md"))
    assert list((board / "completed").glob("task-2 - *.md"))


def test_task_complete_of_a_task_that_is_not_done_is_refused_and_moves_nothing(
    shipped: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "complete", "task-1", "--server", shipped])

    assert (code, doc["code"]) == (1, "refused")
    assert "not Done" in doc["error"]
    assert _task_file(tmp_path).exists()
    assert not (tmp_path / ".starpulse" / "board" / "completed").exists()


def test_task_claim_records_the_session_as_the_assignee_and_names_it(
    lifecycled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "claim", "task-1", "--server", lifecycled], {"STARPULSE_SESSION": "s-7"})

    assert (code, doc) == (
        0,
        {"ok": True, "task": "task-1", "to": "in_progress", "assignee": "s-7", "reason": "", "skill": ""},
    )


def test_task_claim_without_a_session_is_refused_as_invalid(
    lifecycled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "claim", "task-1", "--server", lifecycled])

    assert (code, doc["code"]) == (1, "refused")
    assert "session" in doc["error"]


@pytest.mark.parametrize("verb", [["park", "PROJ-6", "--operator", "choose"], ["review", "PROJ-6", "--ref", PULL]])
def test_task_park_and_review_on_a_board_that_edits_no_task_exit_3_and_say_so(
    verb: list[str], bare: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", *verb, "--server", bare])

    assert (code, doc["code"]) == (3, "unavailable")
    assert "does not edit tasks" in doc["error"]


def test_task_park_picks_the_lane_from_the_reason_given(lifecycled: str, capsys: pytest.CaptureFixture[str]) -> None:
    soak = "{id: soak, kind: prom, expr: up, at_least: 1}"

    waiting = _run(capsys, ["task", "park", "task-2", "--until", soak, "--comment", "soaking", "--server", lifecycled])

    assert waiting == (0, {"ok": True, "task": "task-2", "to": "waiting", "reason": "", "skill": ""})


def test_task_park_on_the_operator_needs_attention(lifecycled: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "park", "task-2", "--operator", "pick a window", "--server", lifecycled])

    assert (code, doc["to"]) == (0, "needs_attention")


@pytest.mark.parametrize(
    "reasons",
    [[], ["--until-task", "task-1", "--operator", "choose"], ["--until", "[1, 2]"], ["--until", "{unclosed"]],
)
def test_task_park_without_exactly_one_valid_reason_is_refused(
    reasons: list[str], lifecycled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "park", "task-2", *reasons, "--server", lifecycled])

    assert (code, doc["code"]) == (1, "refused")


def test_task_review_with_a_pull_request_moves_the_task_and_without_one_names_the_rule_and_skill(
    lifecycled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    refused = _run(capsys, ["task", "review", "task-2", "--server", lifecycled])
    moved = _run(capsys, ["task", "review", "task-2", "--ref", PULL, "--summary", "Shipped", "--server", lifecycled])

    assert refused == (
        1,
        {
            "ok": False,
            "task": "task-2",
            "to": "",
            "reason": "Review needs a pull request in references",
            "skill": "completing-tasks",
        },
    )
    assert moved == (0, {"ok": True, "task": "task-2", "to": "review", "reason": "", "skill": ""})


def test_task_checkpoint_ac_checks_one_criterion_and_records_its_evidence(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "checkpoint-ac", "task-1", "2", "pytest exits 0", "--server", tasked])

    assert (code, doc) == (0, {"task": "task-1", "criterion": 2, "changed": ["acceptanceCriteria"]})
    written = _task_file(tmp_path).read_text()
    assert "- [ ] #1 It draws\n- [x] #2 It scales" in written
    assert "Verified AC #2: pytest exits 0" in written


def test_task_checkpoint_ac_of_a_criterion_the_task_lacks_is_refused_and_writes_nothing(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _task_file(tmp_path).read_text()

    code, doc = _run(capsys, ["task", "checkpoint-ac", "task-1", "3", "pytest exits 0", "--server", tasked])

    assert (code, doc["code"]) == (1, "refused")
    assert "#3" in doc["error"]
    assert _task_file(tmp_path).read_text() == before


def test_task_checkpoint_ac_without_evidence_is_a_usage_error_and_writes_nothing(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _task_file(tmp_path).read_text()

    code, doc = _run(capsys, ["task", "checkpoint-ac", "task-1", "1", "  ", "--server", tasked])

    assert (code, doc["code"]) == (2, "usage")
    assert "evidence" in doc["error"]
    assert _task_file(tmp_path).read_text() == before


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
    assert {"--state", "--milestone", "--label", "--profile", "--assignee", "--server"} <= flags
    assert board["exit_codes"] == [0, 2, 3]
    assert "columns" in board["outputs"]
    show = next(v for v in doc["verbs"] if v["verb"] == "task show")
    assert [(a["name"], a["required"]) for a in show["arguments"] if not a["flags"]] == [("task", True)]


def test_search_sends_each_label_and_the_finished_within_window(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    index = SearchIndex.open(create_engine(f"sqlite:///{tmp_path / 'search.sqlite'}"))
    assert index is not None
    index.index(task("PROJ-1", "To Do", title="Drain", labels=["disk", "unraid"]))
    index.index(task("PROJ-2", "To Do", title="Drain", labels=["disk"]))
    month_ago = time.time() - 31 * 86400
    index.index(
        task("PROJ-3", "Done", title="Drain", labels=["disk", "unraid"], settled="completed", settled_at=month_ago)
    )
    with _serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), search=index) as server:
        argv = ["search", "drain", "--label", "disk", "--label", "unraid", "--finished-within-days", "30"]
        code, doc = _run(capsys, [*argv, "--server", _url(server, "")])

    assert code == 0
    assert [hit["task"] for hit in doc["hits"]] == ["PROJ-1"]


def test_the_manifest_describes_every_verb_and_each_of_its_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    _, doc = _run(capsys, ["help", "--agent"])

    assert [v["verb"] for v in doc["verbs"]] == [
        "snapshot",
        "board",
        "search",
        "task show",
        "task moves",
        "task move",
        "task claim",
        "task park",
        "task review",
        "task trace",
        "task create",
        "task edit",
        "task profile",
        "task archive",
        "task verdict",
        "task miss",
        "task restore",
        "task retire",
        "task retired",
        "task import-retired",
        "task complete",
        "task checkpoint-ac",
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
        "doc restore",
        "runs list",
        "runs start",
        "watch",
        "analytics health",
        "analytics steps",
        "analytics transitions",
        "analytics cells",
        "analytics graph",
        "analytics stages",
        "analytics diff",
        "analytics scores",
        "command run",
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
        "machine": None,
        "path": [{"at": 200.0, "from": None, "to": "to_do"}, {"at": 201.0, "from": "to_do", "to": "ready"}],
        "steps": 2,
    }


def test_task_trace_with_a_flow_is_the_machine_path(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "trace", "PROJ-1", "--machine", "in-progress", "--server", base])

    assert code == 0
    assert doc == {
        "task": "PROJ-1",
        "machine": "in-progress",
        "path": [
            {"at": 100.0, "event": "WORKTREE_READY", "state": "worktree_ready"},
            {"at": 101.0, "event": "RED_PROVEN", "state": "red_proven"},
        ],
        "steps": 2,
    }


def test_task_trace_with_a_flow_takes_a_run_id(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "trace", "run-9", "--machine", "in-progress", "--server", base])

    assert code == 0
    assert doc == {
        "task": "run-9",
        "machine": "in-progress",
        "path": [{"at": 300.0, "event": "WORKTREE_READY", "state": "worktree_ready"}],
        "steps": 1,
    }


def test_task_trace_of_a_task_never_seen_is_an_empty_path(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "trace", "PROJ-99", "--server", base])

    assert (code, doc["path"], doc["steps"]) == (0, [], 0)


def test_task_trace_of_an_unknown_flow_is_not_found(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "trace", "PROJ-1", "--machine", "nowhere", "--server", base])

    assert (code, doc) == (4, {"error": "unknown machine nowhere", "code": "not_found"})


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


def test_analytics_steps_lists_each_model_request_with_its_skill_activities_keys_and_tokens(
    stepped: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", "steps", "--hours", "1.06", "--server", stepped])

    assert code == 0
    assert (doc["now"], doc["window_s"]) == (STEPS_NOW, 1.06 * 3600)
    assert [(s["harness"], s["task"], s["skill"], s["captured"]) for s in doc["steps"]] == [
        ("claude-code", "TASK-1", "none", True)
    ] * 3
    assert [s["keys"] for s in doc["steps"]] == [["Bash"], ["Bash"], []]
    assert set(doc["steps"][0]["tokens"]) == {"input", "output", "cache_read", "cache_write", "reasoning"}


def test_analytics_steps_refuses_a_window_longer_than_the_telemetry_history(
    stepped: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", "steps", "--hours", "24", "--server", stepped])

    assert (code, doc["code"], "longer than the history" in doc["error"]) == (1, "refused", True)


def test_analytics_steps_refuses_a_window_the_server_refuses(stepped: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["analytics", "steps", "--hours", "0", "--server", stepped])

    assert (code, doc["code"], "positive number" in doc["error"]) == (1, "refused", True)


def test_analytics_steps_of_a_server_that_receives_no_telemetry_is_unavailable(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["analytics", "steps", "--server", base])

    assert (code, doc["code"], "telemetry" in doc["error"]) == (3, "unavailable", True)


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
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
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
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
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
    with _canned(
        403, {"error": "Editing a task answers only loopback and private network (RFC 1918) browsers"}, reads
    ) as base:
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
    ("move", {"machine": "in-progress", "id": "PROJ-1", "agent": {"state": "green"}}),
    ("move", {"machine": "in-progress", "id": "PROJ-2", "agent": {"state": "red"}}),
    ("move", {"machine": "deploy", "id": "PROJ-1", "agent": {"state": "live"}}),
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
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
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
    ("analytics steps", 0): ["analytics", "steps", "--hours", "1.06", "--server", "{stepped}"],
    ("analytics steps", 1): ["analytics", "steps", "--hours", "0", "--server", "{stepped}"],
    ("analytics steps", 2): ["analytics", "steps", "--hours", "soon"],
    ("analytics steps", 3): ["analytics", "steps", "--server", "{down}"],
    ("analytics transitions", 0): ["analytics", "transitions", "--hours", "1.06", "--server", "{stepped}"],
    ("analytics transitions", 1): ["analytics", "transitions", "--hours", "0", "--server", "{stepped}"],
    ("analytics transitions", 2): ["analytics", "transitions", "--hours", "soon"],
    ("analytics transitions", 3): ["analytics", "transitions", "--server", "{down}"],
    ("analytics scores", 0): ["analytics", "scores", "--hours", "1.06", "--repo", "o/r", "--server", "{stepped}"],
    ("analytics scores", 1): ["analytics", "scores", "--hours", "0", "--repo", "o/r", "--server", "{stepped}"],
    ("analytics scores", 2): ["analytics", "scores", "--hours", "soon", "--repo", "o/r"],
    ("analytics scores", 3): ["analytics", "scores", "--repo", "o/r", "--server", "{down}"],
    ("analytics cells", 0): ["analytics", "cells", "--hours", "1.06", "--server", "{stepped}"],
    ("analytics cells", 1): ["analytics", "cells", "--hours", "0", "--server", "{stepped}"],
    ("analytics cells", 2): ["analytics", "cells", "--hours", "soon"],
    ("analytics cells", 3): ["analytics", "cells", "--server", "{down}"],
    ("analytics graph", 0): ["analytics", "graph", "--hours", "1.06", "--server", "{stepped}"],
    ("analytics graph", 1): ["analytics", "graph", "--hours", "0", "--server", "{stepped}"],
    ("analytics graph", 2): ["analytics", "graph", "--hours", "soon"],
    ("analytics graph", 3): ["analytics", "graph", "--server", "{down}"],
    ("analytics stages", 0): ["analytics", "stages", "--hours", "0.5", "--server", "{stepped}"],
    ("analytics stages", 1): ["analytics", "stages", "--hours", "0", "--server", "{stepped}"],
    ("analytics stages", 2): ["analytics", "stages", "--hours", "soon"],
    ("analytics stages", 3): ["analytics", "stages", "--server", "{down}"],
    ("analytics diff", 0): ["analytics", "diff", "--hours", "1.06", "--server", "{stepped}"],
    ("analytics diff", 1): ["analytics", "diff", "--hours", "0", "--server", "{stepped}"],
    ("analytics diff", 2): ["analytics", "diff", "--hours", "soon"],
    ("analytics diff", 3): ["analytics", "diff", "--server", "{down}"],
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
    ("task claim", 0): ["task", "claim", "task-1", "--session", "s-1", "--server", "{lifecycled}"],
    ("task claim", 1): ["task", "claim", "task-3", "--session", "s-1", "--server", "{lifecycled}"],
    ("task claim", 2): ["task", "claim"],
    ("task claim", 3): ["task", "claim", "task-1", "--session", "s-1", "--server", "{down}"],
    ("task claim", 4): ["task", "claim", "task-99", "--session", "s-1", "--server", "{lifecycled}"],
    ("task park", 0): ["task", "park", "task-2", "--until-task", "task-1", "--server", "{lifecycled}"],
    ("task park", 1): ["task", "park", "task-1", "--operator", "choose", "--server", "{lifecycled}"],
    ("task park", 2): ["task", "park"],
    ("task park", 3): ["task", "park", "task-2", "--operator", "choose", "--server", "{down}"],
    ("task park", 4): ["task", "park", "task-99", "--operator", "choose", "--server", "{lifecycled}"],
    ("task review", 0): ["task", "review", "task-2", "--ref", PULL, "--server", "{lifecycled}"],
    ("task review", 1): ["task", "review", "task-2", "--server", "{lifecycled}"],
    ("task review", 2): ["task", "review"],
    ("task review", 3): ["task", "review", "task-2", "--ref", PULL, "--server", "{down}"],
    ("task review", 4): ["task", "review", "task-99", "--ref", PULL, "--server", "{lifecycled}"],
    ("task trace", 0): ["task", "trace", "PROJ-1", "--machine", "in-progress", "--server", "{server}"],
    ("task trace", 2): ["task", "trace"],
    ("task trace", 3): ["task", "trace", "PROJ-1", "--server", "{down}"],
    ("task trace", 4): ["task", "trace", "PROJ-1", "--machine", "nowhere", "--server", "{server}"],
    ("task create", 0): ["task", "create", "Rotate the secret", "--server", "{tasked}"],
    ("task create", 1): ["task", "create", " ", "--server", "{tasked}"],
    ("task create", 2): ["task", "create"],
    ("task create", 3): ["task", "create", "Rotate the secret", "--server", "{down}"],
    ("task edit", 0): ["task", "edit", "task-1", "--title", "Draw the lanes", "--server", "{tasked}"],
    ("task edit", 1): ["task", "edit", "task-1", "--title", " ", "--server", "{tasked}"],
    ("task edit", 2): ["task", "edit", "task-1", "--server", "{tasked}"],
    ("task edit", 3): ["task", "edit", "task-1", "--title", "Draw the lanes", "--server", "{down}"],
    ("task edit", 4): ["task", "edit", "task-99", "--title", "Draw the lanes", "--server", "{tasked}"],
    ("task profile", 0): ["task", "profile", "task-1", "@agent-fast-low", "--server", "{tasked}"],
    ("task profile", 1): ["task", "profile", "task-1", "@agent-fast-low", "--server", "{readonly}"],
    ("task profile", 2): ["task", "profile", "task-1"],
    ("task profile", 3): ["task", "profile", "task-1", "@agent-fast-low", "--server", "{down}"],
    ("task profile", 4): ["task", "profile", "task-99", "@agent-fast-low", "--server", "{tasked}"],
    ("task archive", 0): ["task", "archive", "task-1", "--reason", "superseded", "--server", "{tasked}"],
    ("task archive", 1): ["task", "archive", "task-1", "--server", "{readonly}"],
    ("task archive", 2): ["task", "archive"],
    ("task archive", 3): ["task", "archive", "task-1", "--server", "{down}"],
    ("task archive", 4): ["task", "archive", "task-99", "--server", "{tasked}"],
    ("task verdict", 0): [
        "task",
        "verdict",
        "task-1",
        "live",
        "pass",
        "--evidence",
        "it draws",
        "--server",
        "{checked}",
    ],
    ("task verdict", 1): ["task", "verdict", "task-1", "live", "pass", "--server", "{tasked}"],
    ("task verdict", 2): ["task", "verdict", "task-1"],
    ("task verdict", 3): ["task", "verdict", "task-1", "live", "pass", "--server", "{down}"],
    ("task verdict", 4): ["task", "verdict", "task-99", "live", "pass", "--server", "{tasked}"],
    ("task miss", 0): ["task", "miss", "task-1", "live", "--title", "Repair live", "--server", "{checked}"],
    ("task miss", 1): ["task", "miss", "task-1", "live", "--title", "Repair live", "--server", "{tasked}"],
    ("task miss", 2): ["task", "miss", "task-1", "live"],
    ("task miss", 3): ["task", "miss", "task-1", "live", "--title", "Repair live", "--server", "{down}"],
    ("task miss", 4): ["task", "miss", "task-99", "live", "--title", "Repair live", "--server", "{tasked}"],
    ("task restore", 0): ["task", "restore", "task-1", "--server", "{archived}"],
    ("task restore", 1): ["task", "restore", "task-1", "--server", "{tasked}"],
    ("task restore", 2): ["task", "restore"],
    ("task restore", 3): ["task", "restore", "task-1", "--server", "{down}"],
    ("task retire", 0): ["task", "retire", "task-2", "--server", "{retiring}"],
    ("task retire", 1): ["task", "retire", "task-1", "--server", "{retiring}"],
    ("task retire", 2): ["task", "retire"],
    ("task retire", 3): ["task", "retire", "task-2", "--server", "{down}"],
    ("task retired", 0): ["task", "retired", "--server", "{retiring}"],
    ("task retired", 2): ["task", "retired", "--nope"],
    ("task retired", 3): ["task", "retired", "--server", "{down}"],
    ("task import-retired", 0): ["task", "import-retired", "{dir}/retired.md", "--server", "{retiring}"],
    ("task import-retired", 1): ["task", "import-retired", "{dir}/no-id.md", "--server", "{retiring}"],
    ("task import-retired", 2): ["task", "import-retired", "{dir}/nope.md", "--server", "{retiring}"],
    ("task import-retired", 3): ["task", "import-retired", "{dir}/retired.md", "--server", "{down}"],
    ("task complete", 0): ["task", "complete", "task-2", "--server", "{shipped}"],
    ("task complete", 1): ["task", "complete", "task-1", "--server", "{shipped}"],
    ("task complete", 2): ["task", "complete"],
    ("task complete", 3): ["task", "complete", "task-2", "--server", "{down}"],
    ("task complete", 4): ["task", "complete", "task-99", "--server", "{shipped}"],
    ("task checkpoint-ac", 0): ["task", "checkpoint-ac", "task-1", "1", "it draws", "--server", "{tasked}"],
    ("task checkpoint-ac", 1): ["task", "checkpoint-ac", "task-1", "9", "it draws", "--server", "{tasked}"],
    ("task checkpoint-ac", 2): ["task", "checkpoint-ac", "task-1", "1"],
    ("task checkpoint-ac", 3): ["task", "checkpoint-ac", "task-1", "1", "it draws", "--server", "{down}"],
    ("task checkpoint-ac", 4): ["task", "checkpoint-ac", "task-99", "1", "it draws", "--server", "{tasked}"],
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
    ("doc restore", 0): ["doc", "restore", "doc-84", "--folder", "specs", "--server", "{shelved}"],
    ("doc restore", 1): ["doc", "restore", "doc-84", "--server", "{milestoned}"],
    ("doc restore", 2): ["doc", "restore"],
    ("doc restore", 3): ["doc", "restore", "doc-84", "--server", "{down}"],
    ("search", 0): ["search", "signing", "--server", "{searchable}"],
    ("search", 1): ["search", " ", "--server", "{searchable}"],
    ("search", 2): ["search"],
    ("search", 3): ["search", "signing", "--server", "{server}"],
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
    ("command run", 0): ["command", "run", "--config", "{dir}/commands.toml", "pass"],
    ("command run", 1): ["command", "run", "--config", "{dir}/commands.toml", "fail"],
    ("command run", 2): ["command", "run", "--config", "{dir}/commands.toml", "needs-task"],
    ("command run", 3): ["command", "run", "--config", "{dir}/commands.toml", "missing-binary"],
    ("command run", 4): ["command", "run", "--config", "{dir}/commands.toml", "nope"],
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


# An error document that carries a key beyond `error` and `code`: an unmapped command names the fallback.
ERROR_EXTRAS = {("command run", 4): {"fallback"}}

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
    (root / "commands.toml").write_text(
        "[project.commands]\n"
        'pass = ["true"]\n'
        'fail = ["false"]\n'
        'needs-task = ["echo", "{task}"]\n'
        'missing-binary = ["./no-such-binary"]\n'
    )
    (root / "retired.md").write_text("---\nid: task-3\nstatus: Done\n---\n")
    (root / "no-id.md").write_text("no front matter\n")
    (root / "flow.mmd").write_text("stateDiagram-v2\n    [*] --> open\n    open --> closed : Close it\n")
    board = {"agents": [{"id": "PROJ-1", "title": "Rotate the secret", "state": "ready"}]}
    snap = {"now": 1.0, "dags": [], "flows": {"board": board, "in-progress": {"agents": []}}}
    (root / "design" / "data.js").write_text(f"window.SNAP = {json.dumps(snap)};\n")
    (root / "design" / "index.html").write_text('<script src="data.js"></script>')
    return root


SERVERS = {
    "server": "base",
    "stepped": "stepped",
    "movable": "movable",
    "lifecycled": "lifecycled",
    "bare": "bare",
    "runnable": "runnable",
    "forbidden": "forbidden",
    "milestoned": "milestoned",
    "tasked": "tasked",
    "archived": "archived",
    "checked": "checked",
    "shelved": "shelved",
    "shipped": "shipped",
    "readonly": "readonly",
    "searchable": "searchable",
    "retiring": "retiring",
}


def _servers(request: pytest.FixtureRequest, template: Sequence[str]) -> dict[str, str]:
    """The servers a template names, each built only if named: a case never pays for a server it does not use."""
    named = {name for arg in template for _, name, _, _ in string.Formatter().parse(arg)}
    return {name: request.getfixturevalue(fixture) for name, fixture in SERVERS.items() if name in named}


def test_a_manifest_case_builds_only_the_servers_its_template_names(request: pytest.FixtureRequest) -> None:
    for template, built in ((["task", "move", "PROJ-6", "review", "--server", "{bare}"], 1), (["skills", "list"], 0)):
        before = STARTED[0]

        _servers(request, template)

        # the servers are shared (ci/shared_servers.py): one an earlier case built is not built again
        assert STARTED[0] - before <= built


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
    assert set(doc) == (
        set(manifest["outputs"]) if reports else {"error", "code"} | ERROR_EXTRAS.get((verb, exit_code), set())
    )


SKILLS = [
    "authoring-starpulse-machines",
    "deliver",
    "operating-starpulse-board",
    "review-fix",
    "setting-up-starpulse",
    "starting-task",
    "tdd",
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
        (s, "modified" if s == "setting-up-starpulse" else "installed", "absent") for s in SKILLS
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


def test_the_claude_plugin_marketplace_serves_the_bundled_skills() -> None:
    root = skill_install.SOURCE.parents[1]
    marketplace = json.loads((root / ".claude-plugin/marketplace.json").read_text())
    [plugin] = marketplace["plugins"]
    assert plugin["name"] == "starpulse"
    manifest = json.loads((root / plugin["source"] / ".claude-plugin/plugin.json").read_text())
    assert manifest["name"] == plugin["name"]
    assert [(root / plugin["source"] / p).resolve() for p in manifest["skills"]] == [skill_install.SOURCE.resolve()]


def _named_verbs(skill: str, verbs: dict[str, set[str]]) -> list[str]:
    """The manifest verb behind each `starpulse ...` command the skill names, each with its flags checked."""
    named = []
    for span in re.findall(r"`starpulse ([^`]+)`", (skill_install.SOURCE / skill / "SKILL.md").read_text()):
        words = span.split()
        if words[0] == "serve":  # run through their own parsers, not the verb manifest
            continue
        leaf = next((" ".join(words[:n]) for n in (3, 2, 1) if " ".join(words[:n]) in verbs), None)
        assert leaf, f"{skill} names `starpulse {span}`, which is no manifest verb"
        # What follows a bare `--` goes to the project's command, not to the verb.
        options = words[: words.index("--")] if "--" in words else words
        flags = {w.split("=")[0] for w in options if w.startswith("--")}
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
    assert {"task claim", "command run"} <= set(named["starting-task"])


@pytest.mark.parametrize("task", ["proj-1", "PROJ-1", "Proj-1"])
def test_canonical_task_key_is_answered_whichever_case_task_show_is_asked_in(
    task: str, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "show", task, "--server", base])

    assert (code, doc["id"]) == (0, "PROJ-1")


def test_canonical_task_key_is_answered_for_a_settled_task_in_either_case(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "show", "proj-3", "--server", base])

    assert (code, doc["id"]) == (0, "PROJ-3")


def test_task_show_reads_a_cold_done_task_whole_from_the_board_and_a_dependent_no_longer_waits_on_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = time.time()
    record = {
        "title": "Old work",
        "type": "story",
        "profile": "@agent-a",
        "labels": ["x"],
        "milestone": "m-1",
        "dependencies": [],
        "description": "Long ago.",
        "acceptanceCriteria": [{"n": 1, "text": "ships", "checked": True}],
    }
    feed = BoardFeed(roles=ROLES, machines=MACHINES, clock=lambda: now)
    feed.expect("0-0")
    feed.put(task("PROJ-9", "Done", observed_at=now - 2 * HOT_S))
    feed.put(task("PROJ-1", "Ready", dependencies=("PROJ-9",)))

    with _serve(tmp_path, feed, bare_board(read={"PROJ-9": record}.get)) as server:
        _, cold = _run(capsys, ["task", "show", "proj-9", "--server", _url(server, "")])
        _, dependent = _run(capsys, ["task", "show", "PROJ-1", "--server", _url(server, "")])

    assert (cold["lane"], cold["title"], cold["description"], cold["milestone"]) == (
        "done",
        "Old work",
        "Long ago.",
        "m-1",
    )
    assert cold["criteria"] == [{"text": "ships", "checked": True}]
    assert dependent["waiting_on"] == []


def test_board_milestone_lists_the_done_tasks_past_their_hot_day(
    cooled: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, board = _run(capsys, ["board", "--milestone", "m-1", "--server", cooled])

    done = next(column for column in board["columns"] if column["state"] == "done")
    assert code == 0
    assert sorted(t["id"] for t in done["tasks"]) == ["PROJ-1", "PROJ-3", "PROJ-4"]
    assert {t["lane"] for t in done["tasks"]} == {"done"}


def test_a_server_a_manifest_case_names_outlives_the_case_that_built_it(request: pytest.FixtureRequest) -> None:
    """A server per case is the module's cost: a fixture the cases share is built once per worker, not once per case."""
    manager = request.session._fixturemanager
    scopes = {}
    for fixture in SERVERS.values():
        (definition, *_) = manager.getfixturedefs(fixture, request.node)
        scopes[fixture] = definition.scope

    assert {fixture: scope for fixture, scope in scopes.items() if scope == "function"} == {}


def test_the_drop_migration_is_the_only_new_reference_to_starpulse_insights() -> None:
    root = Path(__file__).resolve().parents[3]
    hits = [
        path
        for path in root.rglob("*.py")
        if "tests" not in path.parts and "starpulse_insights" in path.read_text(errors="ignore")
    ]
    assert {path.name for path in hits} == {"0004_insights.py", "0026_drop_insights.py"}


def test_task_retired_milestone_prints_only_that_milestones_tasks(
    retiring: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    held = tmp_path / "held-milestone"
    held.mkdir()
    (held / "task-3 - In.md").write_text("---\nid: task-3\nstatus: Done\nmilestone: m-9\n---\n")
    (held / "task-4 - Out.md").write_text("---\nid: task-4\nstatus: Done\nmilestone: m-8\n---\n")
    _run(capsys, ["task", "import-retired", *map(str, held.iterdir()), "--server", retiring])

    code, body = _run(capsys, ["task", "retired", "--milestone", "m-9", "--server", retiring])

    assert code == 0
    assert [row["task"] for row in body["tasks"]] == ["task-3"]
