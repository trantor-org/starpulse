"""Creating a task through the board: the optional create writer, `POST /api/tasks` and the snapshot's `create` flag."""

import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from starpulse._internal.adapters.boards.seam import Board
from starpulse._internal.adapters.boards.upstream_backlog import UpstreamBacklog, _split
from starpulse._internal.api.adapter_kit import serve, url
from starpulse._internal.api.server import assemble
from starpulse._internal.api.writes import create_task
from starpulse._internal.projections.board_feed import BoardFeed
from starpulse._internal.settings.config import load
from starpulse._internal.store.event_log import EventLog

LAN = "192.168.0.42"


def _raw(**body: object) -> bytes:
    return json.dumps(body).encode()


def _tasks(base: Path) -> Path:
    return base / ".starpulse" / "board" / "tasks"


@pytest.fixture(autouse=True)
def _no_backlog_cli(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """The native board creates with Python alone: nothing named `backlog` is on PATH."""
    monkeypatch.setenv("PATH", str(tmp_path_factory.mktemp("empty-bin")))
    assert shutil.which("backlog") is None


def _serving(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Board, BoardFeed]:
    """The default native board of an empty directory, scanned once on start."""
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval: self.scan())
    built, feed = assemble(load(None), tmp_path, None, ())
    built.start(feed, "test", EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))
    return built, feed


def test_a_create_writes_a_task_file_in_the_first_lane_and_the_next_scan_carries_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, feed = _serving(tmp_path, monkeypatch)
    assert built.create is not None

    first = create_task("127.0.0.1", _raw(title="Draw the board"), built.create)
    second = create_task(LAN, _raw(title="Ship it"), built.create)

    assert first == (201, {"task": "task-1"})
    assert second == (201, {"task": "task-2"})
    files = sorted(path.name for path in _tasks(tmp_path).glob("*.md"))
    assert files == ["task-1 - Draw-the-board.md", "task-2 - Ship-it.md"]
    text = (_tasks(tmp_path) / files[0]).read_text()
    assert "status: To Do\n" in text and "title: Draw the board\n" in text
    UpstreamBacklog(tmp_path / ".starpulse" / "board", feed.put).scan()
    flow, _harness = feed.snapshot()["flows"]
    assert [(agent["id"], agent["title"], agent["state"]) for agent in flow["agents"]] == [
        ("task-1", "Draw the board", "to_do"),
        ("task-2", "Ship it", "to_do"),
    ]


def test_a_create_in_a_board_that_already_holds_tasks_takes_the_next_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, _ = _serving(tmp_path, monkeypatch)
    (_tasks(tmp_path) / "task-7 - Old.md").write_text("---\nid: task-7\ntitle: Old\nstatus: Done\n---\n")
    assert built.create is not None

    assert create_task("127.0.0.1", _raw(title="New"), built.create) == (201, {"task": "task-8"})


def test_a_title_with_a_path_separator_still_makes_one_file_inside_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, _ = _serving(tmp_path, monkeypatch)
    assert built.create is not None

    assert create_task("127.0.0.1", _raw(title="../../escape/now"), built.create)[0] == 201

    written = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*.md"))
    assert len(written) == 1 and written[0].startswith(".starpulse/board/tasks/task-1 - ")


_DETAILS = {
    "description": "Explain the three lanes.\nThen the toolbar.",
    "priority": "High",
    "labels": ["docs", "ui"],
    "milestone": "m-1",
    "assignee": "@agent-fast-low",
    "dependencies": ["task-1"],
    "acceptanceCriteria": ["The quickstart names every lane", "A reader can create a task"],
}


def test_a_create_writes_every_detail_as_backlog_markdown_and_the_next_scan_reads_them_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, feed = _serving(tmp_path, monkeypatch)
    assert built.create is not None
    create_task("127.0.0.1", _raw(title="First"), built.create)

    created = create_task("127.0.0.1", _raw(title="Write the quickstart", **_DETAILS), built.create)

    assert created == (201, {"task": "task-2"})
    frontmatter, body = _split((_tasks(tmp_path) / "task-2 - Write-the-quickstart.md").read_text())
    assert frontmatter == {
        "id": "task-2",
        "title": "Write the quickstart",
        "status": "To Do",
        "assignee": ["@agent-fast-low"],
        "labels": ["docs", "ui"],
        "milestone": "m-1",
        "dependencies": ["task-1"],
        "priority": "high",
    }
    assert (
        "## Acceptance Criteria\n<!-- AC:BEGIN -->\n- [ ] #1 The quickstart names every lane\n"
        "- [ ] #2 A reader can create a task\n<!-- AC:END -->"
    ) in body
    UpstreamBacklog(tmp_path / ".starpulse" / "board", feed.put).scan()
    flow, _harness = feed.snapshot()["flows"]
    agent = next(agent for agent in flow["agents"] if agent["id"] == "task-2")
    assert {key: agent[key] for key in ("state", "model", "labels", "milestone", "dependencies", "description")} == {
        "state": "to_do",
        "model": "@agent-fast-low",
        "labels": ["docs", "ui"],
        "milestone": "m-1",
        "dependencies": ["task-1"],
        "description": "Explain the three lanes.\nThen the toolbar.",
    }


@pytest.mark.parametrize(
    ("details", "field"),
    [
        ({"colour": "red"}, "colour"),
        ({"labels": "docs"}, "labels"),
        ({"labels": [3]}, "labels"),
        ({"priority": "Urgent"}, "priority"),
        ({"description": 5}, "description"),
        ({"acceptanceCriteria": ["Fine", " "]}, "acceptanceCriteria"),
    ],
)
def test_a_create_with_a_wrong_detail_is_a_400_naming_it_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, details: dict, field: str
) -> None:
    built, _ = _serving(tmp_path, monkeypatch)
    assert built.create is not None

    status, body = create_task("127.0.0.1", _raw(title="Fine", **details), built.create)

    assert status == 400 and field in body["error"]
    assert list(_tasks(tmp_path).iterdir()) == []


@pytest.mark.parametrize("raw", [b"not json", _raw(), _raw(title=3), _raw(title="  "), _raw(title="x" * 301)])
def test_a_create_without_a_usable_title_is_a_400_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: bytes
) -> None:
    built, _ = _serving(tmp_path, monkeypatch)
    assert built.create is not None

    status, body = create_task("127.0.0.1", raw, built.create)

    assert status == 400 and "title" in body["error"]
    assert list(_tasks(tmp_path).iterdir()) == []


def test_a_create_from_outside_the_lan_is_refused_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, _ = _serving(tmp_path, monkeypatch)

    status, body = create_task("203.0.113.9", _raw(title="Nope"), built.create)

    assert status == 403 and "loopback" in body["error"]
    assert list(_tasks(tmp_path).iterdir()) == []


def test_a_board_with_no_create_writer_refuses_a_create() -> None:
    status, body = create_task("127.0.0.1", _raw(title="Nope"), None)

    assert status == 404 and "does not create" in body["error"]


def test_post_api_tasks_creates_on_the_native_board_and_answers_405_to_a_get(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, feed = _serving(tmp_path, monkeypatch)
    with serve(tmp_path, feed, create=built.create) as server:
        request = urllib.request.Request(
            url(server, "/api/tasks"),
            data=_raw(title="Over HTTP"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as resp:
            created = (resp.status, json.load(resp))
        with pytest.raises(urllib.error.HTTPError) as got:
            urllib.request.urlopen(url(server, "/api/tasks"), timeout=5)

    assert created == (201, {"task": "task-1"})
    assert (got.value.code, got.value.headers["Allow"]) == (405, "POST")


def test_post_api_tasks_on_a_board_without_create_is_404(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed()) as server:
        request = urllib.request.Request(
            url(server, "/api/tasks"),
            data=_raw(title="Nope"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as got:
            urllib.request.urlopen(request, timeout=5)

    assert got.value.code == 404


@pytest.mark.parametrize(
    ("table", "can_create"),
    [("", True), ('[board]\ntype = "native"\n', True), ('[board]\ntype = "upstream_backlog"\n', False)],
)
def test_the_snapshot_says_whether_the_board_can_create(tmp_path: Path, table: str, can_create: bool) -> None:
    (tmp_path / "backlog").mkdir()
    (tmp_path / "backlog" / "config.yml").write_text("project_name: demo\n")
    (tmp_path / "starpulse.toml").write_text(table)

    built, feed = assemble(load(tmp_path / "starpulse.toml"), tmp_path, None, ())

    assert feed.snapshot()["capabilities"]["create"] is can_create
    assert (built.create is not None) is can_create
