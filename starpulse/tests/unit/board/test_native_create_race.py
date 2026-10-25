"""Concurrent first opens of one absent board: the first creates it whole, every opener finds it complete."""

import threading
from pathlib import Path

import yaml

from starpulse.board.adapters.native import _create

OPENERS = 8


def test_concurrent_creates_of_an_absent_board_all_succeed_and_leave_it_whole(tmp_path: Path) -> None:
    root = tmp_path / ".starpulse" / "board"
    start = threading.Barrier(OPENERS)
    seen: list[object] = []

    def open_board() -> None:
        start.wait()
        try:
            _create(root, "demo")
            seen.append(yaml.safe_load((root / "config.yml").read_text())["project_name"])
        except Exception as error:  # noqa: BLE001 - the test reports whatever an opener hit
            seen.append(error)

    threads = [threading.Thread(target=open_board) for _ in range(OPENERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert seen == ["demo"] * OPENERS
    assert (root / "tasks").is_dir()
    assert [path.name for path in root.parent.iterdir()] == ["board"]
