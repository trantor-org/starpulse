"""`starpulse migrate-proposals` moves the configured board's Proposed tasks to `PROP-N` ids and `--reverse` restores
them from the map it wrote."""

import json
from pathlib import Path

import pytest
from starpulse.board.adapters.native import _split_record
from starpulse.runtime import proposal_ids

from tests.unit.board.test_native import native_root
from tests.unit.board.test_proposal_ids import FIXTURE, _board


def _project(base: Path, monkeypatch: pytest.MonkeyPatch, prefix: str) -> Path:
    """A board with an idea and a real task, and the config that names it; `prefix` is its `proposal_prefix`."""
    built = _board(base, monkeypatch)
    assert built.create is not None
    assert built.create("An idea", {"status": "Proposed"}).ok
    assert built.create("Real work", {"status": "Ready"}).ok
    config = base / "starpulse.toml"
    setting = f'proposal_prefix = "{prefix}"\n' if prefix else ""
    config.write_text(f'[board]\ntype = "native"\nmachine = "{FIXTURE.name}"\n{setting}')
    (base / FIXTURE.name).write_text(FIXTURE.read_text())
    return config


def _ids(base: Path) -> set[str]:
    return {_split_record(path.read_text())[0]["id"] for path in (native_root(base) / "tasks").glob("*.md")}


def test_the_command_migrates_the_proposals_and_reverse_restores_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _project(tmp_path, monkeypatch, "PROP")

    assert proposal_ids.main(["--config", str(config)]) == 0
    assert json.loads(capsys.readouterr().out)["moved"] == 1
    assert _ids(tmp_path) == {"PROP-1", "TASK-2"}

    assert proposal_ids.main(["--config", str(config), "--reverse"]) == 0
    assert json.loads(capsys.readouterr().out)["moved"] == 1
    assert _ids(tmp_path) == {"TASK-1", "TASK-2"}


def test_the_command_refuses_a_board_with_no_proposal_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _project(tmp_path, monkeypatch, "")

    assert proposal_ids.main(["--config", str(config)]) == 1
    assert "no proposal_prefix" in capsys.readouterr().err
    assert _ids(tmp_path) == {"TASK-1", "TASK-2"}
