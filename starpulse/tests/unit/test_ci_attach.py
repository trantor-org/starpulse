"""The `[ci]` config table attaches the shipped CI machine as a sub-flow of named Board states."""

from pathlib import Path

import pytest

from starpulse._internal.api.server import assemble
from starpulse._internal.settings.config import ConfigError, load


def _snapshot(tmp_path: Path, text: str) -> dict:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return assemble(load(path), tmp_path, None, ())[1].snapshot()


def _flows(snapshot: dict) -> dict[str, dict]:
    return {flow["name"]: flow for flow in snapshot["flows"]}


def test_the_ci_machine_is_a_sub_flow_under_each_board_state_the_config_names(tmp_path: Path) -> None:
    flows = _flows(_snapshot(tmp_path, '[ci]\nstates = ["to_do", "in_progress"]\n'))

    link = {"flow": "ci", "exits": {}, "parent": "board", "when": "a PR is open"}
    assert flows["board"]["machine"]["subflows"] == [{"state": "to_do", **link}, {"state": "in_progress", **link}]
    assert flows["ci"]["machine"]["source"] == "GitHub"


def test_without_a_ci_table_the_board_has_no_ci_flow(tmp_path: Path) -> None:
    flows = _flows(_snapshot(tmp_path, ""))

    assert "ci" not in flows
    assert "subflows" not in flows["board"]["machine"]


def test_a_state_the_board_machine_lacks_is_refused_naming_it(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="ci: review is not a state of the board machine"):
        _snapshot(tmp_path, '[ci]\nstates = ["in_progress", "review"]\n')


@pytest.mark.parametrize(
    "table",
    ["[ci]\n", "[ci]\nstates = []\n", "[ci]\nstates = [1]\n", '[ci]\nstates = ["a"]\nextra = 1\n'],
)
def test_a_ci_table_that_is_not_a_list_of_state_names_is_refused(tmp_path: Path, table: str) -> None:
    path = tmp_path / "starpulse.toml"
    path.write_text(table)

    with pytest.raises(ConfigError, match=r"^ci: "):
        load(path)
