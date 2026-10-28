"""A `[board] python_path` puts the deployment's own source on `sys.path` so a `validate` hook living there imports."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from starpulse.board.adapters.native import board


def test_a_python_path_directory_beside_the_config_lets_validate_import_a_module_that_lives_only_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "hooks"
    source.mkdir()
    (source / "only_in_hooks.py").write_text(
        "def check(path, before, after):\n    return 'refused by the hook'\n"
    )
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delitem(sys.modules, "only_in_hooks", raising=False)

    built = board(
        {"python_path": ["hooks"], "validate": "only_in_hooks:check"}, tmp_path
    )

    assert built.create("Draw the board", {}).output == "refused by the hook"
    assert sys.path[0] == str(source.resolve())


def test_a_python_path_entry_that_does_not_exist_fails_the_load_naming_the_key(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError, match=r"board: python_path names no directory: .*absent"
    ):
        board({"python_path": ["absent"]}, tmp_path)
