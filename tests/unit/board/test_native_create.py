"""Concurrent first uses of one absent board create it once, and every caller finds it whole."""

import threading
from collections import Counter
from pathlib import Path

import yaml
from starpulse.board.adapters.native import _create

CALLERS = 8
ROUNDS = 25


def test_concurrent_first_creates_all_find_a_whole_board(tmp_path: Path):
    for round_ in range(ROUNDS):
        root = tmp_path / f"board{round_}"
        gate = threading.Barrier(CALLERS)
        seen: list[object] = []

        def first_use():
            gate.wait()
            try:
                _create(root, "proj")
                seen.append(yaml.safe_load((root / "config.yml").read_text())["project_name"])
                seen.append((root / "tasks").is_dir())
            except Exception as error:
                seen.append(error)

        threads = [threading.Thread(target=first_use) for _ in range(CALLERS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert Counter(map(repr, seen)) == {"'proj'": CALLERS, "True": CALLERS}
