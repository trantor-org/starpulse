"""The `[sequences]` table: the phases a task of each type goes through, in order."""

from pathlib import Path

import pytest
from starpulse.runtime.config import ConfigError, load


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return path


def test_a_sequences_table_maps_each_task_type_to_its_phases(tmp_path: Path) -> None:
    config = load(_write(tmp_path, '[sequences]\nstory = ["build", "qa", "deliver"]\ndefault = ["build", "deliver"]\n'))

    assert config.sequences == {"story": ("build", "qa", "deliver"), "default": ("build", "deliver")}


def test_a_config_without_a_sequences_table_names_none(tmp_path: Path) -> None:
    assert load(_write(tmp_path, "")).sequences == {}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[sequences]\nstory = "build"\n', "story must be a list of phase ids"),
        ("[sequences]\nstory = []\n", "story must be a list of phase ids"),
        ('[sequences]\nstory = ["build", "Qa Phase"]\n', "story: .Qa Phase. is not a phase id"),
        ('[sequences]\nstory = ["build", "build"]\n', "story: build is listed twice"),
    ],
)
def test_a_sequence_that_is_not_a_list_of_distinct_phase_ids_is_refused(
    tmp_path: Path, text: str, message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        load(_write(tmp_path, text))
