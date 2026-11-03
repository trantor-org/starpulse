"""The migration moves every Proposed task to a `PROP-N` id, oldest first, keeps its task number as an alias and
repoints dependencies; the reverse step gives each its task number back from the recorded map."""

import json
from pathlib import Path

import pytest
from starpulse.board.adapters.native import _find, _split_record
from starpulse.board.adapters.proposal_migration import migrate, reverse
from starpulse.board.model.seam import Board

from tests.unit.board.test_native import native_root
from tests.unit.board.test_proposal_ids import _board


def _ids(base: Path) -> dict[str, str]:
    """Each open task file's id to its status."""
    records = [_split_record(path.read_text())[0] for path in (native_root(base) / "tasks").glob("*.md")]
    return {record["id"]: record["status"] for record in records}


def _seeded(base: Path, monkeypatch: pytest.MonkeyPatch) -> Board:
    """A board with no proposal prefix: two proposals, a ready task and a task waiting on the second proposal."""
    built = _board(base, monkeypatch)
    assert built.create is not None
    for title, status, details in (
        ("First idea", "Proposed", {}),
        ("Real work", "Ready", {}),
        ("Second idea", "Proposed", {}),
        ("Needs idea", "Waiting", {"dependencies": ["TASK-3"]}),
    ):
        assert built.create(title, {"status": status, **details}).ok
    return built


def test_migrate_gives_each_proposal_a_proposal_id_and_keeps_its_task_number_as_an_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seeded(tmp_path, monkeypatch)
    root, alias_map = native_root(tmp_path), tmp_path / "alias-map.json"

    moved = migrate(root, "PROP", "proposed", alias_map)

    assert moved == {"TASK-1": "PROP-1", "TASK-3": "PROP-2"}
    assert json.loads(alias_map.read_text()) == moved
    assert _ids(tmp_path) == {"PROP-1": "Proposed", "TASK-2": "Ready", "PROP-2": "Proposed", "TASK-4": "Waiting"}
    assert _find(root, "TASK-3") == _find(root, "PROP-2")
    waiting = _split_record(_find(root, "TASK-4").read_text())[0]  # type: ignore[union-attr]
    assert waiting["dependencies"] == ["PROP-2"]


def test_migrate_twice_changes_nothing_more(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seeded(tmp_path, monkeypatch)
    root, alias_map = native_root(tmp_path), tmp_path / "alias-map.json"
    migrate(root, "PROP", "proposed", alias_map)

    assert migrate(root, "PROP", "proposed", alias_map) == {"TASK-1": "PROP-1", "TASK-3": "PROP-2"}


def test_reverse_restores_the_task_numbers_the_map_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seeded(tmp_path, monkeypatch)
    root, alias_map = native_root(tmp_path), tmp_path / "alias-map.json"
    migrate(root, "PROP", "proposed", alias_map)

    restored = reverse(root, alias_map)

    assert restored == {"TASK-1": "PROP-1", "TASK-3": "PROP-2"}
    assert _ids(tmp_path) == {"TASK-1": "Proposed", "TASK-2": "Ready", "TASK-3": "Proposed", "TASK-4": "Waiting"}
    record = _split_record(_find(root, "TASK-3").read_text())[0]  # type: ignore[union-attr]
    assert "aliases" not in record
    assert _split_record(_find(root, "TASK-4").read_text())[0]["dependencies"] == ["TASK-3"]
