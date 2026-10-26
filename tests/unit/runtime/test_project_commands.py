"""The `[project.commands]` table: a name mapped to an argv, and a malformed entry is refused."""

import re
from pathlib import Path

import pytest
from starpulse.runtime.config import ConfigError, load


def _load(tmp_path: Path, text: str):
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return load(path)


def test_a_table_maps_each_name_to_its_argv(tmp_path: Path) -> None:
    config = _load(
        tmp_path, '[project.commands]\ndeliver = ["./bin/ship", "{task}"]\ntest = ["make", "test", "{args}"]\n'
    )

    assert config.project.commands == {"deliver": ("./bin/ship", "{task}"), "test": ("make", "test", "{args}")}


@pytest.mark.parametrize(
    ("entry", "refusal"),
    [
        ('deliver = "./bin/ship"', "project.commands.deliver: an argv is a list of strings"),
        ("deliver = []", "project.commands.deliver: an argv names at least a program"),
        ('deliver = ["ship", ""]', "project.commands.deliver: element 1 is empty"),
        ('deliver = ["ship", 3]', "project.commands.deliver: an argv is a list of strings"),
        ('deliver = ["ship", "{task"]', "project.commands.deliver: element 1 has an unbalanced brace"),
        ('deliver = ["ship", "x{args}"]', "project.commands.deliver: {args} must be a whole element"),
        ('"Bad Name" = ["ship"]', "project.commands: name 'Bad Name' is not lowercase words joined by hyphens"),
    ],
)
def test_a_malformed_entry_is_refused_naming_it(tmp_path: Path, entry: str, refusal: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(refusal)):
        _load(tmp_path, f"[project.commands]\n{entry}\n")


def test_an_unknown_project_key_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=re.escape("project: unknown key(s) cmds")):
        _load(tmp_path, "[project]\ncmds = {}\n")
