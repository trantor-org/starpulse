"""The upstream Backlog.md adapter: task files in, board contract and a generated Board machine out."""

import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from starpulse.adapter_kit import BoardAdapterKit
from starpulse.board_feed import BoardFeed
from starpulse.contracts import BoardTask
from starpulse.upstream_backlog import (
    BacklogConfig,
    UpstreamBacklog,
    _split,
    board,
    board_machine,
    read_config,
    upstream_keys,
)

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


def write_config(root: Path, statuses: tuple[str, ...] = STATUSES, prefix: str = "task") -> None:
    root.mkdir(parents=True, exist_ok=True)
    listed = ", ".join(f'"{s}"' for s in statuses)
    (root / "config.yml").write_text(f'project_name: "demo"\nstatuses: [{listed}]\ntask_prefix: "{prefix}"\n')


def scanned(root: Path) -> list[BoardTask]:
    tasks: list[BoardTask] = []
    UpstreamBacklog(root, tasks.append).scan()
    return tasks


class TestUpstreamBoardAdapter(BoardAdapterKit):
    keys = upstream_keys("task")
    branches = {"feature/task-12-add-x": "task-12", "refs/heads/task-3": "task-3", "main": None, "task-x": None}
    machines = {"board": board_machine(STATUSES)}

    def produce(self) -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "backlog"
            write_config(root)
            write_task(root, "tasks", "task-1", "To Do", dependencies="[task-2]", assignee="['@ada']", labels="[spike]")
            write_task(root, "tasks", "task-2", "Doing", references="[https://github.com/o/r/pull/9]")
            write_task(root, "completed", "task-3", "Done")
            write_task(root, "archive/tasks", "task-4", "To Do")
            return [task.model_dump(mode="json") for task in scanned(root)]


def test_the_config_names_the_statuses_and_the_task_prefix(tmp_path: Path) -> None:
    write_config(tmp_path, ("Backlog", "Shipped"), prefix="PROJ")

    assert read_config(tmp_path) == BacklogConfig(("Backlog", "Shipped"), "PROJ")


def test_a_project_without_a_config_has_upstream_defaults(tmp_path: Path) -> None:
    assert read_config(tmp_path) == BacklogConfig(("To Do", "In Progress", "Done"), "task")


@pytest.mark.parametrize("text", ["statuses: [unclosed", "- just\n- a list\n", ""])
def test_a_config_that_is_not_a_mapping_has_upstream_defaults(tmp_path: Path, text: str) -> None:
    (tmp_path / "config.yml").write_text(text)

    assert read_config(tmp_path) == BacklogConfig(("To Do", "In Progress", "Done"), "task")


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
    assert keys.for_branch("feature/proj-12-add-x") == "proj-12"
    assert upstream_keys("proj").for_branch("feature/PROJ-12") == "PROJ-12"


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
            title="Title of task-7",
            lane="doing",
            dependencies=("task-2", "task-3"),
            references=("https://github.com/o/r/pull/9", "docs/x.md"),
            assignee="@ada",
            labels=("spike", "ui"),
            description="Why task-7",
        )
    ]


def test_a_task_with_no_assignee_labels_or_description_has_the_contract_defaults(tmp_path: Path) -> None:
    write_config(tmp_path)
    write_task(tmp_path, "tasks", "task-1", "To Do", body="")
    (tmp_path / "tasks" / "task-1 - Title of task-1.md").write_text("---\nid: task-1\ntitle: T\nstatus: To Do\n---\n")

    assert scanned(tmp_path) == [BoardTask(id="task-1", title="T", lane="to_do")]


def test_a_description_without_markers_is_the_text_under_its_heading(tmp_path: Path) -> None:
    write_config(tmp_path)
    write_task(tmp_path, "tasks", "task-1", "To Do", body="Plain words\n\n## Acceptance Criteria\n\n- [ ] x")

    assert scanned(tmp_path)[0].description == "Plain words"


def test_completed_and_archived_files_are_settled(tmp_path: Path) -> None:
    write_config(tmp_path)
    write_task(tmp_path, "completed", "task-1", "Done")
    write_task(tmp_path, "archive/tasks", "task-2", "To Do")

    assert {t.id: t.settled for t in scanned(tmp_path)} == {"task-1": "completed", "task-2": "archived"}


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
    assert (settled["id"], settled["agent"], settled["settled"]) == ("task-1", None, "completed")

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


def test_the_adapter_runs_with_no_redis_stream_and_no_backlog_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("REDIS_URL", "REDIS_PASSWORD", "BACKLOG_PROJECTION_REDIS_HOST", "BACKLOG_PROJECTION_REDIS_PORT"):
        monkeypatch.delenv(name, raising=False)

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("the adapter opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    write_config(tmp_path)
    write_task(tmp_path, "tasks", "task-1", "To Do")

    assert [t.id for t in scanned(tmp_path)] == ["task-1"]


def test_the_adapter_module_pulls_in_neither_redis_nor_the_projection_contract() -> None:
    code = (
        "import sys, starpulse.upstream_backlog;"
        "bad = [m for m in ('redis', 'event_stream', 'backlog_projection', 'backlog_lifecycle') if m in sys.modules];"
        "sys.exit(','.join(bad) or 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=60)

    assert result.returncode == 0, result.stderr or result.stdout


def _started(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, float]]:
    started: list[tuple[Path, float]] = []
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval: started.append((self.root, interval)))
    return started


def test_the_board_reads_the_project_its_path_names_and_polls_at_its_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = _started(monkeypatch)
    write_config(tmp_path / "proj", ("Open", "Shut"), prefix="PROJ")

    built = board({"type": "upstream_backlog", "path": "proj", "interval": "0.5"}, tmp_path)
    built.start(BoardFeed(), "test")

    assert built.source == str(tmp_path / "proj")
    assert built.machines(lambda name: name, ()) == {"board": board_machine(("Open", "Shut"))}
    assert built.keys is not None
    assert built.keys.matches("PROJ-1") and not built.keys.matches("task-1")
    assert started == [(tmp_path / "proj", 0.5)]


def test_without_settings_the_board_reads_backlog_beside_the_config_every_two_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = _started(monkeypatch)

    board({}, tmp_path).start(BoardFeed(), "test")

    assert started == [(tmp_path / "backlog", 2.0)]


def test_a_board_setting_the_adapter_does_not_read_is_refused_beside_the_known_ones(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as refused:
        board({"path": "proj", "colour": "red", "abc": 1}, tmp_path)

    assert str(refused.value) == "board: unknown key(s) abc, colour; known: interval, path, type"
