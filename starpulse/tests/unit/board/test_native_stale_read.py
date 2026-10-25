"""A task edit whose file changed between its read and its write is redone on the new file, so a concurrent move survives."""

from pathlib import Path

from starpulse.board.adapters import native
from starpulse.board.adapters.native import _comment, _update


def test_edit_keeps_a_status_another_writer_set_after_its_read(tmp_path: Path) -> None:
    (tasks := tmp_path / "tasks").mkdir()
    path = tasks / "task-1 - demo.md"
    path.write_text("---\nid: TASK-1\nstatus: Ready\n---\n\nbody\n")
    reads: list[int] = []

    def comment(_: dict, body: str) -> str:
        reads.append(1)
        if len(reads) == 1:  # another writer lands its move after this edit's read
            path.write_text(path.read_text().replace("status: Ready", "status: In Progress"))
        return _comment(body, "claimed")

    assert native._update(tmp_path, "TASK-1", comment).ok

    text = path.read_text()
    assert "status: In Progress" in text
    assert "claimed" in text
    assert len(reads) == 2
    assert [p.name for p in tasks.iterdir()] == [path.name]


def test_edit_gives_up_when_the_file_keeps_changing(tmp_path: Path) -> None:
    (tasks := tmp_path / "tasks").mkdir()
    path = tasks / "task-1 - demo.md"
    path.write_text("---\nid: TASK-1\nstatus: Ready\n---\n\nbody\n")

    def comment(_: dict, body: str) -> str:
        path.write_text(path.read_text() + "x")  # a writer lands after every read
        return body

    written = _update(tmp_path, "TASK-1", comment)

    assert not written.ok
    assert "changed" in written.output
