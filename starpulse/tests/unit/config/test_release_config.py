"""The `[release]` table: its presence starts the release of Waiting tasks, and `settle` names a stricter rule than Done."""

from pathlib import Path

import pytest

from starpulse._internal.config.config import ConfigError, Release, load

REPOS = '[[repos]]\nname = "starpulse"\npath = "starpulse"\napplied_by = "pin-bump"\n'


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return path


def test_no_table_releases_nothing(tmp_path: Path) -> None:
    assert load(None).release is None
    assert load(_write(tmp_path, REPOS)).release is None


def test_an_empty_table_releases_a_task_once_its_dependencies_are_done(tmp_path: Path) -> None:
    assert load(_write(tmp_path, "[release]\n")).release == Release(settle=None)


def test_the_pin_bump_rule_is_named_by_the_release_table(tmp_path: Path) -> None:
    config = load(_write(tmp_path, f'{REPOS}\n[release]\nsettle = "pin-bump"\n'))

    assert config.release == Release(settle="pin-bump")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (f'{REPOS}\n[release]\nsettle = "merged"\n', "settle must be pin-bump"),
        ('[release]\nwhen = "now"\n', "the .release. table takes only settle"),
        ('[release]\nsettle = "pin-bump"\n', "settle = pin-bump needs a .\\[repos\\]. entry"),
    ],
)
def test_a_release_table_the_server_cannot_apply_is_refused(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load(_write(tmp_path, text))
