"""Every board adapter's tasks are searchable once the adapter has been read: one index, whatever the source."""

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event

from starpulse._internal.board import native, upstream_backlog
from starpulse._internal.board.upstream_backlog import UpstreamBacklog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.feed.search import SearchIndex
from starpulse.tests.integration.board.test_jira import project, recorded_site, serve

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "native_board"
_STATUSES = 'project_name: "demo"\nstatuses: ["Waiting", "Done"]\ntask_prefix: "task"\n'

#: Sets up one board's root over the recorded task files, as Backlog.md itself wrote them, and returns it with its machines.
Place = Callable[[Path], tuple[Path, dict]]


def _native(base: Path) -> tuple[Path, dict]:
    """A fresh native board in `base`, then the recorded task files copied into it."""
    root = base / ".starpulse" / "board"
    root.mkdir(parents=True)
    (root / "config.yml").write_text(_STATUSES)
    for folder in ("tasks", "completed"):
        shutil.copytree(FIXTURES / folder, root / folder)
    built = native.board({}, base)
    return root, built.machines(lambda name: name, ())


def _upstream(base: Path) -> tuple[Path, dict]:
    """The same task files as an upstream Backlog.md project holds them."""
    root = base / "backlog"
    root.mkdir()
    (root / "config.yml").write_text(_STATUSES)
    for folder in ("tasks", "completed"):
        shutil.copytree(FIXTURES / folder, root / folder)
    built = upstream_backlog.board({"path": "backlog", "command": "true"}, base)
    return root, built.machines(lambda name: name, ())


@pytest.fixture(params=[_native, _upstream], ids=["native", "upstream"])
def place(request: pytest.FixtureRequest) -> Place:
    return request.param


def _index(base: Path) -> tuple[SearchIndex, object]:
    engine = create_engine(f"sqlite:///{base / 'search.sqlite'}")
    index = SearchIndex.open(engine)
    assert index is not None
    return index, engine


def _read(root: Path, machines: dict, index: SearchIndex) -> None:
    """What a server does on first serve: a feed that keeps `index`, and the adapter's first scan into it."""
    feed = BoardFeed(machines=machines)
    feed.index_tasks(index)
    UpstreamBacklog(root, feed.put, retract=feed.retract).scan()


def _found(index: SearchIndex, query: str) -> list[str]:
    return [hit["task"] for hit in index.search(query)]


def test_a_board_is_searchable_by_title_description_criteria_and_notes_after_its_first_read(
    place: Place, tmp_path: Path
) -> None:
    root, machines = place(tmp_path)
    index, _ = _index(tmp_path)

    _read(root, machines, index)

    assert _found(index, "Frigate") == ["TASK-1566"]  # a title word
    assert _found(index, "declared writers") == ["TASK-3201"]  # two description words
    assert _found(index, "skill-eval mock") == ["TASK-3201"]  # an acceptance criterion
    assert _found(index, "specview") == ["TASK-2529"]  # a note of a completed task
    assert _found(index, "Holder") == []  # the claim marker is not text


def test_an_edited_description_is_found_by_its_new_text_after_the_next_read(place: Place, tmp_path: Path) -> None:
    root, machines = place(tmp_path)
    index, _ = _index(tmp_path)
    _read(root, machines, index)
    path = next((root / "tasks").glob("task-1566-*.md"))

    path.write_text(
        path.read_text().replace(
            "## Description",
            "## Description\n\n<!-- SECTION:DESCRIPTION:BEGIN -->\nQuarantine the camera feed.\n<!-- SECTION:DESCRIPTION:END -->\n",
            1,
        )
    )
    _read(root, machines, index)

    assert _found(index, "quarantine") == ["TASK-1566"]


def test_a_task_file_that_is_gone_is_no_longer_found(place: Place, tmp_path: Path) -> None:
    root, machines = place(tmp_path)
    index, _ = _index(tmp_path)
    feed = BoardFeed(machines=machines)
    feed.index_tasks(index)
    backlog = UpstreamBacklog(root, feed.put, retract=feed.retract)
    backlog.scan()

    next((root / "tasks").glob("task-1566-*.md")).unlink()
    backlog.scan()

    assert _found(index, "Frigate") == []


def test_a_restart_that_reads_an_unchanged_board_rewrites_no_index_row(place: Place, tmp_path: Path) -> None:
    root, machines = place(tmp_path)
    index, engine = _index(tmp_path)
    _read(root, machines, index)
    writes: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, *rest) -> None:
        writes.append(statement)

    reopened = SearchIndex.open(engine)
    assert reopened is not None
    _read(root, machines, reopened)

    assert [s for s in writes if s.lstrip().upper().startswith(("INSERT", "DELETE", "UPDATE"))] == []
    assert _found(reopened, "Frigate") == ["TASK-1566"]


def test_a_jira_project_is_searchable_after_its_first_read_and_an_edited_description_by_its_new_text(
    tmp_path: Path,
) -> None:
    index, _ = _index(tmp_path)
    site = recorded_site()
    with serve(site) as url:
        jira = project(url)
        feed = BoardFeed(machines={"board": jira.machine})
        feed.index_tasks(index)
        jira.scan(feed.put, feed.retract)

        assert _found(index, "tokenise") == ["PAY-2"]  # a summary
        assert _found(index, "accept") == ["PAY-1"]  # a description

        site.pages[""]["issues"][0]["fields"]["description"] = "Authorise, then capture."
        jira.scan(feed.put, feed.retract)

    assert _found(index, "authorise") == ["PAY-1"]
    assert _found(index, "accept") == []
