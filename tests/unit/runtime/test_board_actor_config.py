"""The `[board.actor]` table: its presence starts the task actor, and it is no setting of the board adapter."""

from pathlib import Path

import pytest
from starpulse.runtime.config import ConfigError, load


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return path


def test_no_table_starts_no_actor(tmp_path: Path) -> None:
    assert load(None).task_actor is False
    assert load(_write(tmp_path, '[board]\ntype = "native"\n')).task_actor is False


def test_an_empty_table_starts_the_actor_and_leaves_the_adapters_settings_without_it(tmp_path: Path) -> None:
    config = load(_write(tmp_path, '[board]\ntype = "native"\ninterval = 1\n[board.actor]\n'))

    assert config.task_actor is True
    assert config.board == {"type": "native", "interval": 1}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[board.actor]\nevery = 5\n", "the .board.actor. table takes no keys"),
        ("[board]\nactor = true\n", "board.actor must be a \\[board.actor\\] table"),
    ],
)
def test_an_actor_table_the_server_cannot_apply_is_refused(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load(_write(tmp_path, text))
