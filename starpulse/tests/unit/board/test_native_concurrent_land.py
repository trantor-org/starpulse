"""Two writers of one task file never share a scratch file: both renames land, neither finds its scratch gone."""

import threading
from pathlib import Path

from starpulse.board.adapters import native
from starpulse.board.adapters.native import OPERATOR, _Guard, _land


def test_two_concurrent_writes_of_one_task_file_both_land(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "task-1 - demo.md"
    path.write_text("---\nid: TASK-1\n---\n")
    both_written = threading.Barrier(2, timeout=5)
    real_replace = native.os.replace

    def replace_after_both_wrote(source, target) -> None:
        both_written.wait()  # each writer has put its scratch down; the renames now race
        real_replace(source, target)

    monkeypatch.setattr(native.os, "replace", replace_after_both_wrote)
    errors: list[BaseException] = []

    def write(n: int) -> None:
        try:
            _land(path, None, {"id": "TASK-1", "writer": n}, "\n", _Guard(), OPERATOR)
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert "writer:" in path.read_text()
    assert [p.name for p in tmp_path.iterdir()] == [path.name]
