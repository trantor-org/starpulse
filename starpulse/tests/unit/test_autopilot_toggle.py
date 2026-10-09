"""The autopilot's switch is a file beside the config, so it survives a restart and needs no config edit."""

from pathlib import Path

import pytest

from starpulse._internal.autopilot.toggle import Toggle


def test_the_autopilot_starts_off(tmp_path: Path) -> None:
    assert Toggle(tmp_path / "starpulse-autopilot.json").get() is False


def test_the_switch_persists_across_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "starpulse-autopilot.json"
    Toggle(path).set(True)

    assert Toggle(path).get() is True  # a new instance is a restarted server

    Toggle(path).set(False)

    assert Toggle(path).get() is False


@pytest.mark.parametrize("text", ["", "not json", "[]", '{"enabled": "yes"}', '{"enabled": 1}', "{}"])
def test_a_file_that_does_not_say_true_leaves_it_off(tmp_path: Path, text: str) -> None:
    path = tmp_path / "starpulse-autopilot.json"
    path.write_text(text)

    assert Toggle(path).get() is False
