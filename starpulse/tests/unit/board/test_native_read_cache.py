"""A repeat read of the native board's task, doc and milestone files does the file work only for what changed."""

import shutil
from pathlib import Path

import pytest

from starpulse._internal.board import native, native_docs, native_milestones

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures" / "native_board"


def _task(root: Path, name: str, task_id: str, title: str) -> Path:
    path = root / ".starpulse" / "board" / "tasks" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {task_id}\ntitle: {title}\nstatus: To Do\n---\n\n## Description\nBody\n")
    return path


@pytest.fixture
def listings(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Every folder the native board lists with a glob."""
    seen: list[Path] = []
    glob = Path.glob

    def counting(self: Path, *args, **kwargs):
        seen.append(self)
        return glob(self, *args, **kwargs)

    monkeypatch.setattr(Path, "glob", counting)
    return seen


def test_a_repeat_task_read_does_not_list_the_board_again(tmp_path: Path, listings: list[Path]) -> None:
    built = native.board({}, tmp_path)
    for number in range(30):
        _task(tmp_path, f"task-{number} - Title", f"task-{number}", f"Title {number}")
    assert built.read is not None
    built.read("task-7")
    listed = len(listings)

    record = built.read("task-7")

    assert record is not None and record["title"] == "Title 7"
    assert len(listings) == listed


def test_a_task_read_follows_a_file_renamed_or_moved_since_the_last_read(tmp_path: Path) -> None:
    built = native.board({}, tmp_path)
    path = _task(tmp_path, "task-7 - Old", "task-7", "Old title")
    assert built.read is not None
    built.read("task-7")
    path.rename(path.with_name("task-7 - New.md"))
    path.with_name("task-7 - New.md").write_text(path.with_name("task-7 - New.md").read_text().replace("Old", "New"))

    record = built.read("task-7")

    assert record is not None and record["title"] == "New title"
    path.with_name("task-7 - New.md").unlink()
    assert built.read("task-7") is None


def test_a_repeat_doc_list_parses_no_file_again_and_follows_an_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = native.board({}, tmp_path)
    docs = tmp_path / ".starpulse" / "board" / "docs"
    shutil.copytree(FIXTURES / "docs", docs)
    assert built.docs is not None
    built.docs()
    parsed: list[str] = []
    load = native_docs.yaml.load
    monkeypatch.setattr(native_docs.yaml, "load", lambda *args, **kwargs: parsed.append("x") or load(*args, **kwargs))

    first = built.docs()

    assert parsed == []
    [doc] = list(docs.rglob("doc-*.md"))
    doc.write_text(doc.read_text().replace("Nightly infrastructure audit", "Weekly audit"))
    [changed] = built.docs()
    assert changed["title"].startswith("Weekly audit") and first[0]["title"].startswith("Nightly")
    assert parsed == ["x"]


def test_a_repeat_milestone_list_parses_no_file_again_and_follows_an_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = native.board({}, tmp_path)
    milestones = tmp_path / ".starpulse" / "board" / "milestones"
    shutil.copytree(FIXTURES / "milestones", milestones)
    assert built.milestones is not None
    built.milestones()
    parsed: list[str] = []
    split = native_milestones._split
    monkeypatch.setattr(native_milestones, "_split", lambda text: parsed.append(text) or split(text))

    first = built.milestones()

    assert parsed == []
    [path] = list(milestones.glob("m-*.md"))
    path.write_text(path.read_text().replace("StarPulse gitlink promotes", "Renamed gitlink promotes"))
    [changed] = built.milestones()
    assert changed["title"] != first[0]["title"]
    assert len(parsed) == 1
