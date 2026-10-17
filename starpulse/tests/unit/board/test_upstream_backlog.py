"""The upstream Backlog.md adapter: task files in, board contract and a generated Board machine out."""

import json
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from starpulse._internal.board import upstream_backlog
from starpulse._internal.board.upstream_backlog import (
    BacklogConfig,
    UpstreamBacklog,
    _split,
    board,
    board_machine,
    board_moves,
    read_config,
    upstream_keys,
)
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import BoardAdapterKit
from starpulse._internal.machines.machine_definition import Writer
from starpulse._internal.server.writes import move_task
from starpulse.contracts.adapters import BoardTask, Move

STATUSES = ("To Do", "Doing", "Review", "Done")


def write_task(root: Path, folder: str, task_id: str, status: str, **fields: object) -> Path:
    """One task file as upstream Backlog.md writes it: YAML frontmatter, then the description section."""
    title = fields.pop("title", f"Title of {task_id}")
    body = fields.pop("body", f"<!-- SECTION:DESCRIPTION:BEGIN -->\nWhy {task_id}\n<!-- SECTION:DESCRIPTION:END -->")
    extra = "".join(f"{key}: {value}\n" for key, value in fields.items())
    path = root / folder / f"{task_id} - {title}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {task_id}\ntitle: {title}\nstatus: {status}\n{extra}---\n\n## Description\n\n{body}\n")
    return path


def write_config(
    root: Path, statuses: tuple[str, ...] = STATUSES, prefix: str = "task", project: str | None = "demo"
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    listed = ", ".join(f'"{s}"' for s in statuses)
    named = "" if project is None else f'project_name: "{project}"\n'
    (root / "config.yml").write_text(f'{named}statuses: [{listed}]\ntask_prefix: "{prefix}"\n')


def scanned(root: Path) -> list[BoardTask]:
    tasks: list[BoardTask] = []
    UpstreamBacklog(root, tasks.append).scan()
    return tasks


class TestUpstreamBoardAdapter(BoardAdapterKit):
    keys = upstream_keys("task")
    teams = {"task-1": "demo", "task-2": "demo", "task-3": "demo", "task-4": "demo"}
    branches = {"feature/task-12-add-x": "task-12", "refs/heads/task-3": "task-3", "main": None, "task-x": None}

    @pytest.fixture(autouse=True)
    def _project(self, tmp_path: Path) -> None:
        """The fixture project: its `Doing` task may go to Review by anyone and back to To Do only by the operator."""
        (tmp_path / "board.yaml").write_text(_OPERATOR_ONLY)
        root = tmp_path / "backlog"
        write_config(root)
        write_task(root, "tasks", "task-1", "To Do", dependencies="[task-2]", assignee="['@ada']", labels="[spike]")
        write_task(root, "tasks", "task-2", "Doing", references="[https://github.com/o/r/pull/9]")
        write_task(root, "completed", "task-3", "Done")
        write_task(root, "archive/tasks", "task-4", "To Do")
        command = fake_cli(tmp_path / "fake-backlog", _FAKE_BACKLOG.format(python=sys.executable))
        built = board({"command": command, "machine": "board.yaml"}, tmp_path)
        self.root, self.writer, self.machines = root, built.writer, built.machines(lambda name: name, ())
        self.moves = board_moves(self.machines["board"], {"RETURN": (Writer("operator", "manual"),)})

    def produce(self) -> list[dict]:
        tasks: list[BoardTask] = []
        UpstreamBacklog(self.root, tasks.append, self.moves).scan()
        return [task.model_dump(mode="json") for task in tasks]


def test_the_config_names_the_statuses_and_the_task_prefix(tmp_path: Path) -> None:
    write_config(tmp_path, ("Backlog", "Shipped"), prefix="PROJ")

    assert read_config(tmp_path) == BacklogConfig(("Backlog", "Shipped"), "PROJ", "demo")


def test_a_project_without_a_config_has_upstream_defaults(tmp_path: Path) -> None:
    assert read_config(tmp_path) == BacklogConfig(("To Do", "In Progress", "Done"), "task", "")


@pytest.mark.parametrize("text", ["statuses: [unclosed", "- just\n- a list\n", ""])
def test_a_config_that_is_not_a_mapping_has_upstream_defaults(tmp_path: Path, text: str) -> None:
    (tmp_path / "config.yml").write_text(text)

    assert read_config(tmp_path) == BacklogConfig(("To Do", "In Progress", "Done"), "task", "")


def test_every_task_is_in_the_team_the_projects_name_gives(tmp_path: Path) -> None:
    write_config(tmp_path, project="Payments")
    write_task(tmp_path, "tasks", "task-1", "To Do")
    write_task(tmp_path, "completed", "task-2", "Done")

    assert {task.id: task.team for task in scanned(tmp_path)} == {"task-1": "Payments", "task-2": "Payments"}


@pytest.mark.parametrize("project", [None, "", "  "], ids=["no project_name", "empty", "blank"])
def test_a_project_that_names_no_project_is_refused_rather_than_given_a_default_team(
    tmp_path: Path, project: str | None
) -> None:
    root = tmp_path / "backlog"
    write_config(root, project=project)
    write_task(root, "tasks", "task-1", "To Do")

    with pytest.raises(ValueError, match=r"config\.yml.*project_name"):
        UpstreamBacklog(root, lambda task: None)
    with pytest.raises(ValueError, match=r"config\.yml.*project_name"):
        board({}, tmp_path)


def test_the_prefix_sets_the_task_keys() -> None:
    keys = upstream_keys("PROJ")

    assert [keys.matches(k) for k in ("PROJ-12", "proj-12", "PROJ-1.2", "OPS-1", "PROJ-x")] == [
        True,
        True,
        True,
        False,
        False,
    ]
    assert keys.for_branch("feature/PROJ-12-add-x") == "PROJ-12"
    assert keys.for_branch("feature/proj-12-add-x") == "PROJ-12"
    assert upstream_keys("proj").for_branch("feature/PROJ-12") == "proj-12"


def test_the_board_machine_has_a_lane_per_configured_status_that_any_status_reaches() -> None:
    machine = board_machine(STATUSES)

    assert [(s["id"], s["name"], s["initial"], s["final"]) for s in machine["states"]] == [
        ("to_do", "To Do", True, False),
        ("doing", "Doing", False, False),
        ("review", "Review", False, False),
        ("done", "Done", False, True),
    ]
    assert {(t["source"], t["target"], t["event"]) for t in machine["transitions"]} == {
        (a, b, f"to_{b}")
        for a in ("to_do", "doing", "review", "done")
        for b in ("to_do", "doing", "review", "done")
        if a != b
    }
    assert machine["mainLine"] == ["to_do", "doing", "review", "done"]


def test_a_task_file_becomes_a_board_task(tmp_path: Path) -> None:
    write_config(tmp_path)
    write_task(
        tmp_path,
        "tasks",
        "task-7",
        "Doing",
        assignee="\n  - '@ada'\n  - '@bo'",
        labels="[spike, ui]",
        dependencies="[task-2, task-3]",
        references="[https://github.com/o/r/pull/9, docs/x.md]",
    )

    assert scanned(tmp_path) == [
        BoardTask(
            id="task-7",
            team="demo",
            title="Title of task-7",
            lane="doing",
            dependencies=("task-2", "task-3"),
            references=("https://github.com/o/r/pull/9", "docs/x.md"),
            assignee="@ada",
            labels=("spike", "ui"),
            description="Why task-7",
            moves={lane: Move(allowed=True) for lane in ("to_do", "review", "done")},
        )
    ]


@pytest.mark.parametrize(
    ("created", "updated", "expected"),
    [
        ("'2026-10-06 07:00'", "'2026-10-06 08:30'", (1791270000.0, 1791275400.0)),
        ("2026-10-06", "2026-10-07", (1791244800.0, 1791331200.0)),
        ("'not a date'", "''", (None, None)),
    ],
    ids=["a UTC minute", "a bare date", "no date it can read"],
)
def test_a_task_carries_its_created_date_and_a_settled_one_its_last_update_as_when_it_settled(
    tmp_path: Path, created: str, updated: str, expected: tuple
) -> None:
    write_config(tmp_path)
    write_task(tmp_path, "tasks", "task-1", "To Do", created_date=created, updated_date=updated)
    write_task(tmp_path, "completed", "task-2", "Done", created_date=created, updated_date=updated)

    open_, settled = scanned(tmp_path)

    assert (open_.created_at, open_.settled_at) == (expected[0], None)
    assert (settled.created_at, settled.settled_at) == expected


def _notes(*lines: str) -> str:
    return "<!-- SECTION:NOTES:BEGIN -->\n" + "\n".join(lines) + "\n<!-- SECTION:NOTES:END -->"


@pytest.mark.parametrize(
    ("notes", "holder"),
    [
        (
            _notes("**Holder:** 0d617371-1999-5360-a76f-a26c28d4878d", "Wired the writer."),
            "0d617371-1999-5360-a76f-a26c28d4878d",
        ),
        (_notes("**Holder:** first", "text", "**Holder:** second"), "second"),  # a later claim by another session wins
        (_notes("Wired the writer."), ""),
        (_notes("see **Holder:** quoted mid-line"), ""),
    ],
)
def test_the_holder_is_the_last_marker_line_in_the_notes(tmp_path: Path, notes: str, holder: str) -> None:
    write_config(tmp_path)
    task = write_task(tmp_path, "tasks", "task-1", "To Do")
    task.write_text(task.read_text() + f"\n## Implementation Notes\n\n{notes}\n")

    assert [t.holder for t in scanned(tmp_path)] == [holder]


def test_a_marker_outside_the_notes_section_is_not_a_holder(tmp_path: Path) -> None:
    write_config(tmp_path)
    write_task(tmp_path, "tasks", "task-1", "To Do", body="**Holder:** in-the-description")

    assert [t.holder for t in scanned(tmp_path)] == [""]


_CRITERIA_TWO_OF_FOUR = (
    "<!-- SECTION:DESCRIPTION:BEGIN -->\nWhy\n<!-- SECTION:DESCRIPTION:END -->\n\n## Acceptance Criteria\n\n"
    "<!-- AC:BEGIN -->\n- [x] #1 first\n- [ ] #2 second\n- [X] #3 third\n- [ ] #4 fourth\n<!-- AC:END -->"
)


def test_a_task_carries_which_of_its_criteria_are_checked_in_file_order(tmp_path: Path) -> None:
    write_config(tmp_path)
    write_task(tmp_path, "tasks", "task-1", "To Do", body=_CRITERIA_TWO_OF_FOUR)

    [task] = scanned(tmp_path)

    assert task.acceptance_criteria == ("first", "second", "third", "fourth")
    assert task.acceptance_checked == (True, False, True, False)


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        ("Doing", "Why\n\n## Needs attention\n\nRestart the server.\nThen rerun deliver.", ""),
        (
            "Needs attention",
            "Why\n\n## Needs attention\n\nRestart the server.\nThen rerun deliver.",
            "Restart the server.",
        ),
        ("Needs attention", "Why\n\n## Needs attention\n\n\n  Pick one.  \n\n## Other\n\nelse", "Pick one."),
        ("Needs attention", "Why, with no reason section", ""),
    ],
    ids=["a task not paused", "the first line of the section", "trimmed, before the next heading", "no section"],
)
def test_a_needs_attention_task_carries_the_first_line_of_its_reason_section(
    tmp_path: Path, status: str, body: str, reason: str
) -> None:
    write_config(tmp_path, statuses=("To Do", "Doing", "Needs attention"))
    description = f"<!-- SECTION:DESCRIPTION:BEGIN -->\n{body}\n<!-- SECTION:DESCRIPTION:END -->"
    write_task(tmp_path, "tasks", "task-1", status, body=description)

    assert [t.pause_reason for t in scanned(tmp_path)] == [reason]


def test_a_task_with_no_assignee_labels_or_description_has_the_contract_defaults(tmp_path: Path) -> None:
    write_config(tmp_path)
    write_task(tmp_path, "tasks", "task-1", "To Do", body="")
    (tmp_path / "tasks" / "task-1 - Title of task-1.md").write_text("---\nid: task-1\ntitle: T\nstatus: To Do\n---\n")

    assert scanned(tmp_path) == [
        BoardTask(
            id="task-1",
            title="T",
            team="demo",
            lane="to_do",
            moves={lane: Move(allowed=True) for lane in ("doing", "review", "done")},
        )
    ]


def test_a_description_without_markers_is_the_text_under_its_heading(tmp_path: Path) -> None:
    write_config(tmp_path)
    write_task(tmp_path, "tasks", "task-1", "To Do", body="Plain words\n\n## Acceptance Criteria\n\n- [ ] x")

    assert scanned(tmp_path)[0].description == "Plain words"


def test_completed_and_archived_files_are_settled(tmp_path: Path) -> None:
    write_config(tmp_path)
    write_task(tmp_path, "completed", "task-1", "Done")
    write_task(tmp_path, "archive/tasks", "task-2", "To Do")

    assert {t.id: t.settled for t in scanned(tmp_path)} == {"task-1": "completed", "task-2": "archived"}


def _scan_with_retractions(root: Path) -> tuple[UpstreamBacklog, list[BoardTask], list[str]]:
    tasks: list[BoardTask] = []
    gone: list[str] = []
    return UpstreamBacklog(root, tasks.append, retract=gone.append), tasks, gone


def test_a_task_whose_file_is_deleted_between_scans_is_retracted(tmp_path: Path) -> None:
    write_config(tmp_path)
    path = write_task(tmp_path, "tasks", "task-1", "To Do")
    write_task(tmp_path, "tasks", "task-2", "To Do")
    backlog, _, gone = _scan_with_retractions(tmp_path)
    backlog.scan()

    path.unlink()
    backlog.scan()
    backlog.scan()

    assert gone == ["task-1"]


def test_a_task_file_moved_to_the_archive_is_settled_not_retracted(tmp_path: Path) -> None:
    write_config(tmp_path)
    path = write_task(tmp_path, "tasks", "task-1", "To Do")
    backlog, tasks, gone = _scan_with_retractions(tmp_path)
    backlog.scan()

    path.unlink()
    write_task(tmp_path, "archive/tasks", "task-1", "To Do")
    backlog.scan()

    assert gone == []
    assert [(t.id, t.settled) for t in tasks] == [("task-1", None), ("task-1", "archived")]


def test_a_status_the_config_does_not_list_is_skipped_and_one_in_other_case_is_matched(tmp_path: Path) -> None:
    write_config(tmp_path)
    write_task(tmp_path, "tasks", "task-1", "Mystery")
    write_task(tmp_path, "tasks", "task-2", "doing")

    assert {t.id: t.lane for t in scanned(tmp_path)} == {"task-2": "doing"}


def test_a_skipped_status_is_logged_with_the_file_that_has_it(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    write_config(tmp_path)
    path = write_task(tmp_path, "tasks", "task-1", "Mystery")

    scanned(tmp_path)

    assert str(path) in caplog.text
    assert "Mystery" in caplog.text


@pytest.mark.parametrize("missing", ["id", "title", "status"])
def test_a_file_missing_its_id_title_or_status_is_skipped(tmp_path: Path, missing: str) -> None:
    write_config(tmp_path)
    (tmp_path / "tasks").mkdir()
    fields = {"id": "task-1", "title": "T", "status": "To Do"} | {missing: ""}
    frontmatter = "".join(f"{k}: '{v}'\n" for k, v in fields.items())
    (tmp_path / "tasks" / "t.md").write_text(f"---\n{frontmatter}---\n")

    assert scanned(tmp_path) == []


def test_a_file_that_is_no_task_is_skipped(tmp_path: Path) -> None:
    write_config(tmp_path)
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "notes.md").write_text("no frontmatter\n")
    (tmp_path / "tasks" / "broken.md").write_text("---\nid: [unclosed\n---\n")
    write_task(tmp_path, "tasks", "task-1", "To Do")

    assert [t.id for t in scanned(tmp_path)] == ["task-1"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("---\nid: a\n---\nbody", ({"id": "a"}, "\nbody")),
        ("---\r\nid: a\r\n---\r\nbody", ({"id": "a"}, "\nbody")),
        ("---\nid: a\n---\nx\n---\ny", ({"id": "a"}, "\nx\n---\ny")),
        ("---\n---\nbody", (None, "")),
        ("---\n\n---\nbody", (None, "\nbody")),
        ("---\nid: a\n", (None, "")),
        ("title\n---\nbody", (None, "")),
        ("x---\nid: a\n---\nbody", (None, "")),
        ("---\nid: [unclosed\n---\nbody", (None, "")),
        ("plain", (None, "")),
    ],
)
def test_a_task_file_splits_into_its_frontmatter_and_the_markdown_after_it(text: str, expected: tuple) -> None:
    assert _split(text) == expected


@pytest.mark.skipif(not yaml.__with_libyaml__, reason="this PyYAML build has no libyaml")
def test_the_frontmatter_is_parsed_by_libyaml_when_the_build_has_it(monkeypatch: pytest.MonkeyPatch) -> None:
    loaders: list[type] = []
    load = yaml.load

    def spy(stream: str, Loader: type) -> object:  # noqa: N803 - PyYAML's keyword
        loaders.append(Loader)
        return load(stream, Loader=Loader)

    monkeypatch.setattr(yaml, "load", spy)

    assert _split("---\nid: a\n---\nbody") == ({"id": "a"}, "\nbody")
    assert loaders == [yaml.CSafeLoader]


def test_a_file_that_cannot_be_read_is_retried_by_the_next_scan_and_does_not_hide_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(tmp_path)
    write_task(tmp_path, "tasks", "task-1", "To Do")
    write_task(tmp_path, "tasks", "task-2", "To Do")
    seen: list[str] = []
    adapter = UpstreamBacklog(tmp_path, lambda t: seen.append(t.id))
    real = Path.read_text

    def flaky(self: Path) -> str:
        if self.name.startswith("task-1 "):
            raise OSError("moved while scanning")
        return real(self)

    monkeypatch.setattr(Path, "read_text", flaky)
    adapter.scan()
    assert seen == ["task-2"]

    monkeypatch.setattr(Path, "read_text", real)
    adapter.scan()
    assert seen == ["task-2", "task-1"]


def test_moving_a_task_file_between_statuses_reaches_the_page_as_a_board_event(tmp_path: Path) -> None:
    write_config(tmp_path)
    task = write_task(tmp_path, "tasks", "task-1", "To Do")
    machine = board_machine(read_config(tmp_path).statuses)
    feed = BoardFeed(keys=upstream_keys(), machines={"board": machine})
    adapter = UpstreamBacklog(tmp_path, feed.put)
    _, events = feed.subscribe()
    adapter.scan()
    assert events.get_nowait() == (
        "task",
        {"id": "task-1", "agent": feed.snapshot()["flows"][0]["agents"][0], "settled": None},
    )

    task.write_text(task.read_text().replace("status: To Do", "status: Review"))
    adapter.scan()
    _, moved = events.get_nowait()
    assert (moved["id"], moved["agent"]["state"], moved["settled"]) == ("task-1", "review", None)

    (tmp_path / "completed").mkdir()
    done = task.rename(tmp_path / "completed" / task.name)
    done.write_text(done.read_text().replace("status: Review", "status: Done"))
    adapter.scan()
    _, settled = events.get_nowait()
    assert (settled["id"], settled["agent"], settled["settled"]["state"]) == ("task-1", None, "completed")

    board = feed.snapshot()["flows"][0]
    assert [s["id"] for s in board["machine"]["states"]] == ["to_do", "doing", "review", "done"]
    assert board["agents"] == []


def test_a_scan_publishes_only_the_files_that_changed(tmp_path: Path) -> None:
    write_config(tmp_path)
    task = write_task(tmp_path, "tasks", "task-1", "To Do")
    write_task(tmp_path, "tasks", "task-2", "To Do")
    seen: list[str] = []
    adapter = UpstreamBacklog(tmp_path, lambda t: seen.append(t.id))

    adapter.scan()
    adapter.scan()
    task.write_text(task.read_text().replace("To Do", "Doing"))
    adapter.scan()

    assert seen == ["task-1", "task-2", "task-1"]


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_start_scans_in_the_background_and_picks_up_a_file_written_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(tmp_path)
    arrived = threading.Event()
    seen: list[str] = []

    def put(task: BoardTask) -> None:
        seen.append(task.id)
        arrived.set()

    adapter = UpstreamBacklog(tmp_path, put)
    thread = adapter.start(interval=0.01)
    write_task(tmp_path, "tasks", "task-1", "To Do")

    assert arrived.wait(timeout=5)
    assert seen == ["task-1"]
    assert thread.daemon
    # The loop has no stop switch, so SystemExit from scan ends it. Left running, it calls
    # time.sleep inside whatever test the worker runs next, and a test that patches time.sleep records it.
    monkeypatch.setattr(adapter, "scan", lambda: (_ for _ in ()).throw(SystemExit))
    thread.join(timeout=5)
    assert not thread.is_alive(), "the polling thread outlived its test and keeps calling time.sleep"


def test_the_adapter_runs_with_no_network_transport_and_no_backlog_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = "re" + "dis"
    for name in (f"{client.upper()}_URL", f"{client.upper()}_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("the adapter opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    write_config(tmp_path)
    write_task(tmp_path, "tasks", "task-1", "To Do")

    assert [t.id for t in scanned(tmp_path)] == ["task-1"]


def test_the_adapter_module_pulls_in_neither_the_legacy_client_nor_the_projection_contract() -> None:
    client = "re" + "dis"
    code = (
        "import sys, starpulse._internal.board.upstream_backlog;"
        f"bad = [m for m in ({client!r}, 'event_stream', 'backlog_projection', 'board_client') if m in sys.modules];"
        "sys.exit(','.join(bad) or 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=60)

    assert result.returncode == 0, result.stderr or result.stdout


def _started(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, float]]:
    started: list[tuple[Path, float]] = []
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval, **_: started.append((self.root, interval)))
    return started


def test_the_board_reads_the_project_its_path_names_and_polls_at_its_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = _started(monkeypatch)
    write_config(tmp_path / "proj", ("Open", "Shut"), prefix="PROJ")

    built = board({"type": "upstream_backlog", "path": "proj", "interval": "0.5"}, tmp_path)
    built.start(BoardFeed(), "test", EventLog("sqlite://"))

    assert built.source == str(tmp_path / "proj")
    assert built.machines(lambda name: name, ()) == {"board": board_machine(("Open", "Shut"))}
    assert built.keys is not None
    assert built.keys.matches("PROJ-1") and not built.keys.matches("task-1")
    assert started == [(tmp_path / "proj", 0.5)]


def test_without_settings_the_board_reads_backlog_beside_the_config_and_backs_its_watch_up_every_minute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = _started(monkeypatch)
    write_config(tmp_path / "backlog")

    board({}, tmp_path).start(BoardFeed(), "test", EventLog("sqlite://"))

    assert started == [(tmp_path / "backlog", 60.0)]


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_the_first_scan_is_the_feeds_replay_and_the_feed_is_ready_once_it_has_placed_every_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A cold start places every task file; while it runs the feed builds no Ledger per task and a write waits for it.
    write_config(tmp_path / "backlog")
    for task_id in ("task-1", "task-2"):
        write_task(tmp_path / "backlog", "tasks", task_id, "To Do")
    feed = BoardFeed()
    replayed_at_put: list[bool] = []
    put = feed.put
    monkeypatch.setattr(feed, "put", lambda task: (replayed_at_put.append(feed.wait_replayed(timeout=0)), put(task)))

    others = set(threading.enumerate())  # a board an earlier test left watching sleeps for its backstop scan
    board({"interval": "0.01"}, tmp_path).start(feed, "test", EventLog("sqlite://"))

    assert feed.ready.wait(timeout=5)
    assert replayed_at_put == [False, False]
    assert sorted(task["id"] for task in feed.open_tasks()) == ["task-1", "task-2"]
    monkeypatch.setattr(UpstreamBacklog, "scan", lambda self: (_ for _ in ()).throw(SystemExit))
    for thread in set(threading.enumerate()) - others:
        if thread.name == "upstream-backlog":
            thread.join(timeout=5)
            assert not thread.is_alive(), "the polling thread outlived its test"


def test_stop_all_ends_a_board_waiting_out_a_long_interval(tmp_path: Path) -> None:
    write_config(tmp_path / "backlog")
    write_task(tmp_path / "backlog", "tasks", "task-1", "To Do")
    feed = BoardFeed()
    board({"interval": "3600"}, tmp_path).start(feed, "test", EventLog("sqlite://"))
    assert feed.ready.wait(timeout=5)
    assert any(t.name == "upstream-backlog" for t in threading.enumerate())

    upstream_backlog.stop_all()

    assert not any(t.name == "upstream-backlog" for t in threading.enumerate())


class _DeafWatch:
    """A watch that never hears a file change, so a server left running by a test reads no file the test edits next."""

    def __init__(self, _folders: object) -> None:
        self._woken = threading.Event()

    def wait(self, timeout: float) -> None:
        self._woken.wait(timeout)

    def wake(self) -> None:
        self._woken.set()

    def close(self) -> None:
        pass


def _restarted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[BoardFeed, list[str]]:
    """A server start over `tmp_path`'s board and log: the feed once ready, and the task files its first scan read."""
    read: list[str] = []
    monkeypatch.setattr(upstream_backlog, "DirWatch", _DeafWatch)
    parse = UpstreamBacklog._task
    monkeypatch.setattr(
        UpstreamBacklog, "_task", lambda self, path, *a: (read.append(path.name), parse(self, path, *a))[1]
    )
    feed = BoardFeed()
    # one scan per start: the poll that follows it sleeps past the test
    board({"interval": "3600"}, tmp_path).start(feed, "test", EventLog(f"sqlite:///{tmp_path / 'log.sqlite'}"))
    assert feed.ready.wait(timeout=5)
    return feed, read


def _lanes(feed: BoardFeed) -> dict[str, str]:
    return {task["id"]: task["state"] for task in feed.open_tasks()}


def test_a_restart_over_unchanged_task_files_resumes_the_saved_board_without_reading_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # what a placement derives beside the task comes back too: the pull requests it cites, the criteria it waits on
    root = tmp_path / "backlog"
    write_config(root, (*STATUSES, "Waiting"))
    pull = "https://github.com/acme/demo/pull/7"
    write_task(root, "tasks", "task-1", "Review", references=f"[{pull}]")
    write_task(root, "completed", "task-2", "Done", references=f"[{pull}]")
    gate = "## Start Criteria\n```yaml\nstart_criteria:\n  - id: soak\n    kind: prom\n    expr: up\n    equals: 1\n```"
    section = f"<!-- SECTION:DESCRIPTION:BEGIN -->\n{gate}\n<!-- SECTION:DESCRIPTION:END -->"
    write_task(root, "tasks", "task-3", "Waiting", body=section)
    first, read = _restarted(tmp_path, monkeypatch)
    assert len(read) == 3
    first.save()  # as `serve` does on its way out

    resumed, read = _restarted(tmp_path, monkeypatch)

    assert read == []
    assert _lanes(resumed) == _lanes(first) == {"task-1": "review", "task-3": "waiting"}
    assert resumed.cited("task-1") == resumed.cited("task-2") == [pull]
    assert resumed._gated == first._gated == {"task-3"}


def test_a_task_file_added_edited_or_removed_while_the_server_was_down_is_placed_on_the_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "backlog"
    write_config(root)
    write_task(root, "tasks", "task-1", "To Do")
    gone = write_task(root, "tasks", "task-2", "To Do")
    kept = write_task(root, "tasks", "task-3", "To Do")
    first, _ = _restarted(tmp_path, monkeypatch)
    first.save()
    edited = write_task(root, "tasks", "task-1", "Review")
    gone.unlink()
    added = write_task(root, "tasks", "task-4", "Doing")

    resumed, read = _restarted(tmp_path, monkeypatch)

    assert sorted(read) == sorted([edited.name, added.name])
    assert kept.name not in read
    assert _lanes(resumed) == {"task-1": "review", "task-3": "to_do", "task-4": "doing"}


@pytest.mark.parametrize("saved", ["other code", "unreadable"])
def test_a_saved_board_from_other_code_or_one_that_cannot_be_read_is_replaced_by_a_full_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, saved: str
) -> None:
    write_config(tmp_path / "backlog")
    for task_id in ("task-1", "task-2"):
        write_task(tmp_path / "backlog", "tasks", task_id, "To Do")
    first, _ = _restarted(tmp_path, monkeypatch)
    first.save()
    if saved == "other code":
        monkeypatch.setattr(upstream_backlog, "_PROJECTION", (*upstream_backlog._PROJECTION, "json"))
    else:
        with sqlite3.connect(tmp_path / "log.sqlite") as db:
            assert db.execute("UPDATE starpulse_board_state SET state = '{\"open\": 1}'").rowcount == 1

    resumed, read = _restarted(tmp_path, monkeypatch)

    assert sorted(read) == ["task-1 - Title of task-1.md", "task-2 - Title of task-2.md"]
    assert _lanes(resumed) == {"task-1": "to_do", "task-2": "to_do"}


def test_a_board_setting_the_adapter_does_not_read_is_refused_beside_the_known_ones(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as refused:
        board({"path": "proj", "colour": "red", "abc": 1}, tmp_path)

    assert str(refused.value) == "board: unknown key(s) abc, colour; known: command, interval, machine, path, type"


#: A fake `backlog` CLI: `task edit <id> -s <status>` rewrites that task's status in the project it runs in, as upstream does.
_FAKE_BACKLOG = """\
#!{python}
import re, sys
from pathlib import Path
args = sys.argv[1:]
assert args[:2] == ["task", "edit"] and args[3] == "-s", args
for path in (Path.cwd() / "backlog" / "tasks").glob("*.md"):
    text = path.read_text()
    if f"id: {{args[2]}}\\n" in text:
        text = re.sub(r"^status: .*$", f"status: {{args[4]}}", text, count=1, flags=re.M)
        if args[5:6] == ["--append-notes"]:
            text += f"\\n## Implementation Notes\\n\\n<!-- SECTION:NOTES:BEGIN -->\\n{{args[6]}}\\n<!-- SECTION:NOTES:END -->\\n"
        path.write_text(text)
        print(f"Updated task {{args[2]}}")
        sys.exit(0)
sys.exit("no such task")
"""


def fake_cli(path: Path, source: str) -> str:
    path.write_text(source)
    path.chmod(0o755)
    return str(path)


def project(tmp_path: Path, **settings: object):
    """A fixture Backlog.md project with a task in `Doing`, and the board its settings build."""
    root = tmp_path / "backlog"
    write_config(root)
    task = write_task(root, "tasks", "task-1", "Doing")
    command = fake_cli(tmp_path / "fake-backlog", _FAKE_BACKLOG.format(python=sys.executable))
    return task, board({"command": command, **settings}, tmp_path)


def test_a_task_offers_a_move_to_every_other_lane_that_any_actor_may_make(tmp_path: Path) -> None:
    root = tmp_path / "backlog"
    write_config(root)
    write_task(root, "tasks", "task-1", "Doing")
    write_task(root, "completed", "task-2", "Done")

    moves = {task.id: task.moves for task in scanned(root)}

    assert moves["task-1"] == {lane: Move(allowed=True) for lane in ("to_do", "review", "done")}
    assert moves["task-2"] == {}


def test_the_board_writer_sets_the_status_in_the_task_file_through_the_backlog_cli(tmp_path: Path) -> None:
    task, built = project(tmp_path)

    written = built.writer("task-1", "Review", "operator")

    assert written.ok, written.output
    assert "status: Review\n" in task.read_text()


def claiming_project(tmp_path: Path):
    """A fixture project whose lanes include `In Progress`, the lane a claim moves a task to."""
    root = tmp_path / "backlog"
    write_config(root, ("To Do", "In Progress", "Review", "Done"))
    write_task(root, "tasks", "task-1", "To Do")
    command = fake_cli(tmp_path / "fake-backlog", _FAKE_BACKLOG.format(python=sys.executable))
    return root, board({"command": command}, tmp_path)


def test_an_agent_claim_with_a_session_records_it_as_the_holder_in_the_same_edit(tmp_path: Path) -> None:
    root, built = claiming_project(tmp_path)

    written = built.writer("task-1", "In Progress", "agent", "0d617371-1999-5360-a76f-a26c28d4878d")

    assert written.ok, written.output
    assert "status: In Progress\n" in next((root / "tasks").glob("*.md")).read_text()
    assert [t.holder for t in scanned(root)] == ["0d617371-1999-5360-a76f-a26c28d4878d"]


@pytest.mark.parametrize(
    ("status", "actor", "session"),
    [("Review", "agent", "s1"), ("In Progress", "agent", ""), ("In Progress", "operator", "s1")],
)
def test_only_an_agent_claim_that_names_a_session_records_a_holder(
    tmp_path: Path, status: str, actor: str, session: str
) -> None:
    root, built = claiming_project(tmp_path)

    assert built.writer("task-1", status, actor, session).ok
    assert [t.holder for t in scanned(root)] == [""]


def test_the_board_writer_names_the_configured_status_a_lane_stands_for(tmp_path: Path) -> None:
    root = tmp_path / "backlog"
    write_config(root, ("Open", "QA", "Shut"))
    task = write_task(root, "tasks", "task-1", "Open")
    command = fake_cli(tmp_path / "fake-backlog", _FAKE_BACKLOG.format(python=sys.executable))

    written = board({"command": command}, tmp_path).writer("task-1", "Qa", "agent")

    assert written.ok, written.output
    assert "status: QA\n" in task.read_text()


def test_a_failed_backlog_cli_write_is_refused_with_its_output(tmp_path: Path) -> None:
    task, built = project(tmp_path)

    written = built.writer("task-9", "Review", "agent")

    assert (written.ok, written.output) == (False, "no such task")
    assert "status: Doing\n" in task.read_text()


def test_a_backlog_cli_that_cannot_run_is_refused_by_name(tmp_path: Path) -> None:
    write_config(tmp_path / "backlog")

    written = board({"command": str(tmp_path / "missing")}, tmp_path).writer("task-1", "Done", "agent")

    assert not written.ok and str(tmp_path / "missing") in written.output


_OPERATOR_ONLY = """\
name: board
states:
  to_do: {initial: true}
  doing: {}
  review: {}
  done: {final: true}
events:
  to_doing: [{from: [to_do, review], to: doing}]
  RETURN: [{from: doing, to: to_do}]
  to_review: [{from: doing, to: review}]
  to_done: [{from: review, to: done}]
writers:
  RETURN: [{actor: operator, trigger: manual}]
"""


def machine_project(tmp_path: Path):
    machine = tmp_path / "board.yaml"
    machine.write_text(_OPERATOR_ONLY)
    return project(tmp_path, machine="board.yaml")


def test_a_machines_cues_are_the_boards_cues_beside_the_lane_their_event_reaches(tmp_path: Path) -> None:
    (tmp_path / "board.yaml").write_text(
        _OPERATOR_ONLY
        + "cues:\n"
        + "  - {event: to_done, dag: dagu/apply-on-merge, on: push to main, resolves: forced}\n"
    )
    write_config(tmp_path / "backlog")

    built = board({"command": "backlog", "machine": "board.yaml"}, tmp_path)

    assert built.cues(lambda name: name) == [
        {
            "event": "to_done",
            "dag": "dagu/apply-on-merge",
            "on": "push to main",
            "resolves": "forced",
            "grace": 300,
            "state": "done",
        }
    ]


def test_a_cue_on_an_event_that_reaches_two_lanes_is_refused(tmp_path: Path) -> None:
    (tmp_path / "board.yaml").write_text(
        _OPERATOR_ONLY.replace(
            "to_done: [{from: review, to: done}]", "to_done: [{from: review, to: done}, {from: doing, to: review}]"
        )
        + "cues:\n  - {event: to_done, dag: dagu/apply-on-merge, on: push to main, resolves: next}\n"
    )
    write_config(tmp_path / "backlog")

    with pytest.raises(ValueError, match="cues on event to_done, which must reach exactly one lane"):
        board({"command": "backlog", "machine": "board.yaml"}, tmp_path)


def test_a_machine_without_cues_gives_the_board_none(tmp_path: Path) -> None:
    _, built = machine_project(tmp_path)

    assert built.cues(lambda name: name) == []


def served(built, monkeypatch: pytest.MonkeyPatch) -> BoardFeed:
    """A feed the board's tasks are on after one scan."""
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval, scanned: (self.scan(), scanned()))
    feed = BoardFeed(machines=built.machines(lambda name: name, ()), keys=built.keys)
    built.start(feed, "test", EventLog("sqlite://"))
    return feed


def test_a_machine_file_gives_the_board_its_transitions_and_each_moves_writers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, built = machine_project(tmp_path)

    feed = served(built, monkeypatch)

    (flow,) = feed.snapshot()["flows"]
    assert {t["event"] for t in flow["machine"]["transitions"]} == {"to_doing", "RETURN", "to_review", "to_done"}
    assert flow["agents"][0]["moves"] == {
        "to_do": {"allowed": True, "reason": "", "skill": "", "writers": ("operator",)},
        "review": {"allowed": True, "reason": "", "skill": "", "writers": ()},
    }


def test_an_agent_is_refused_a_move_the_machine_leaves_to_the_operator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, built = machine_project(tmp_path)
    feed = served(built, monkeypatch)

    def move(actor: str) -> tuple[int, dict]:
        raw = json.dumps({"task": "task-1", "to": "to_do", "actor": actor}).encode()
        return move_task("127.0.0.1", raw, feed, built.writer)

    refused = move("agent")
    assert refused[0] == 409 and "operator" in refused[1]["error"]
    assert "status: Doing\n" in task.read_text()
    assert move("operator") == (200, {"task": "task-1", "to": "to_do"})
    assert "status: To Do\n" in task.read_text()


def test_a_machine_file_whose_states_are_not_the_projects_lanes_is_refused(tmp_path: Path) -> None:
    write_config(tmp_path / "backlog")
    (tmp_path / "board.yaml").write_text(
        _OPERATOR_ONLY.replace("  doing: {}\n", "  working: {}\n").replace("doing", "working")
    )

    with pytest.raises(ValueError, match="doing"):
        board({"machine": "board.yaml"}, tmp_path)


def test_a_task_carries_the_text_of_each_acceptance_criterion_checked_or_not(tmp_path: Path) -> None:
    write_config(tmp_path)
    task = write_task(tmp_path, "tasks", "task-1", "To Do")
    task.write_text(
        task.read_text()
        + "\n## Acceptance Criteria\n<!-- AC:BEGIN -->\n- [x] #1 It draws\n- [ ] #2 It scrolls\n<!-- AC:END -->\n"
    )

    assert scanned(tmp_path)[0].acceptance_criteria == ("It draws", "It scrolls")


def test_a_task_carries_its_notes_without_the_holder_marker(tmp_path: Path) -> None:
    write_config(tmp_path)
    task = write_task(tmp_path, "tasks", "task-1", "To Do")
    task.write_text(
        task.read_text()
        + "\n## Implementation Notes\n\n"
        + _notes("**Holder:** 0d617371", "Wired the writer.", "Second line")
        + "\n"
    )

    assert scanned(tmp_path)[0].notes == "Wired the writer.\nSecond line"


@contextmanager
def _watching(root: Path, **kwargs: object) -> Iterator[list[BoardTask]]:
    """An adapter started with an hour between full scans, so only the file watch can place a file written later; its
    thread is ended on exit by a file whose placement raises SystemExit, as the watch is the only thing that wakes it."""
    write_config(root)
    placed: list[BoardTask] = []
    first = threading.Event()
    adapter = UpstreamBacklog(root, placed.append, **kwargs)
    thread = adapter.start(interval=3600, scanned=first.set)
    assert first.wait(timeout=5)
    try:
        yield placed
    finally:
        adapter.scan_files = lambda _paths: (_ for _ in ()).throw(SystemExit)  # type: ignore[method-assign]
        (root / "tasks").mkdir(exist_ok=True)
        (root / "tasks" / "stop.md").write_text("stop")
        thread.join(timeout=5)
        assert not thread.is_alive(), "the watch thread outlived its test"


def _await(condition: Callable[[], bool]) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not condition():
        time.sleep(0.01)
    return condition()


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_file_written_after_start_reaches_the_feed_with_no_scan_interval_elapsing(tmp_path: Path) -> None:
    with _watching(tmp_path) as placed:
        write_task(tmp_path, "tasks", "task-1", "To Do")

        # the new folder triggers a full scan that can read the file the moment the write lands, then the close event
        # places it again; the feed takes a repeat as a no-op, so what matters is that the task arrives
        assert _await(lambda: {t.id for t in placed} == {"task-1"})


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_file_edited_after_start_is_placed_again(tmp_path: Path) -> None:
    write_config(tmp_path)
    write_task(tmp_path, "tasks", "task-1", "To Do")
    with _watching(tmp_path) as placed:
        write_task(tmp_path, "tasks", "task-1", "Doing")

        assert _await(lambda: [t.lane for t in placed] == ["to_do", "doing"])


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_task_file_moved_to_completed_settles_its_task_and_retracts_nothing(tmp_path: Path) -> None:
    write_config(tmp_path)
    path = write_task(tmp_path, "tasks", "task-1", "Done")
    retracted: list[str] = []
    with _watching(tmp_path, retract=retracted.append) as placed:
        (tmp_path / "completed").mkdir(exist_ok=True)
        path.rename(tmp_path / "completed" / path.name)

        assert _await(lambda: [t.settled for t in placed] == [None, "completed"])
        assert retracted == []


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_task_file_deleted_after_start_is_retracted(tmp_path: Path) -> None:
    write_config(tmp_path)
    path = write_task(tmp_path, "tasks", "task-1", "To Do")
    retracted: list[str] = []
    with _watching(tmp_path, retract=retracted.append):
        path.unlink()

        assert _await(lambda: retracted == ["task-1"])


def test_a_done_file_a_watch_sees_leave_for_the_retired_store_is_settled_done_again(tmp_path: Path) -> None:
    write_config(tmp_path)
    path = write_task(tmp_path, "completed", "task-3", "Done")
    text = path.read_text()
    answered = False

    def retired(force: bool) -> Iterator[str] | None:
        """The retired text once, then unchanged until a scan asks for it again."""
        nonlocal answered
        if answered and not force:
            return None
        answered = True
        return iter([text])

    placed: list[BoardTask] = []
    retracted: list[str] = []
    adapter = UpstreamBacklog(tmp_path, placed.append, retract=retracted.append, retired=retired)
    adapter.scan()
    path.unlink()

    adapter.scan_files([path])

    assert retracted == ["task-3"]
    assert [(t.id, t.lane) for t in placed] == [("task-3", "done"), ("task-3", "done")]


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_an_idle_adapter_stats_no_task_file_between_full_scans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_config(tmp_path)
    for number in range(20):
        write_task(tmp_path, "tasks", f"task-{number}", "To Do")
    with _watching(tmp_path):
        statted: list[Path] = []
        real = Path.stat

        def counting(self: Path, **kwargs: object) -> object:
            statted.append(self)
            return real(self, **kwargs)

        monkeypatch.setattr(Path, "stat", counting)
        time.sleep(1.0)

        # an earlier test's watcher thread may still be winding down in this worker: count only this board's files
        assert [path for path in statted if path.suffix == ".md" and tmp_path in path.parents] == []


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_board_without_inotify_still_polls_at_its_interval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_folders: object) -> None:
        raise OSError("no inotify")

    monkeypatch.setattr(upstream_backlog, "DirWatch", refuse)
    write_config(tmp_path)
    placed: list[BoardTask] = []
    adapter = UpstreamBacklog(tmp_path, placed.append)
    thread = adapter.start(interval=0.01)

    write_task(tmp_path, "tasks", "task-1", "To Do")

    assert _await(lambda: [t.id for t in placed] == ["task-1"])
    monkeypatch.setattr(adapter, "scan", lambda: (_ for _ in ()).throw(SystemExit))
    thread.join(timeout=5)
    assert not thread.is_alive()
