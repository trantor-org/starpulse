"""The `[autopilot]` block: every default the ADR's decision 6 names works with no block, and each can be overridden."""

from pathlib import Path

import pytest

from starpulse._internal.autopilot.probe import LocalProbe
from starpulse._internal.config.autopilot import DIMENSIONS, Autopilot
from starpulse._internal.config.config import ConfigError, load


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return path


def test_no_block_resolves_every_default_but_the_starter(tmp_path: Path) -> None:
    for config in (load(None), load(_write(tmp_path, ""))):
        autopilot = config.autopilot

        assert autopilot == Autopilot()
        assert autopilot.eligible_lane("to_do") == "to_do"  # the board's initial lane
        assert autopilot.tier_weights == {"fast": 1, "standard": 2, "deep": 4}
        assert autopilot.unsized_points == 3
        assert autopilot.review_lane == "review"
        assert autopilot.idle_minutes == 30
        assert set(autopilot.limits) == set(DIMENSIONS) == {"cpu", "memory", "sessions", "review"}
        assert all(limit > 0 for limit in autopilot.limits.values())
    assert callable(LocalProbe())  # the local CPU and memory probe is the sampler's default


def test_a_block_overrides_each_default(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[autopilot]
lane = "ready"
review_lane = "qa"
unsized_points = 5
idle_minutes = 10

[autopilot.tier_weights]
standard = 3

[autopilot.limits]
sessions = 4
review = 30
""",
    )

    autopilot = load(path).autopilot

    assert autopilot.eligible_lane("to_do") == "ready"
    assert autopilot.review_lane == "qa"
    assert autopilot.unsized_points == 5
    assert autopilot.idle_minutes == 10
    assert autopilot.tier_weights == {"fast": 1, "standard": 3, "deep": 4}
    assert autopilot.limits["sessions"] == 4 and autopilot.limits["review"] == 30
    assert autopilot.limits["cpu"] == Autopilot().limits["cpu"]  # a limit left out keeps its default


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("[autopilot]\nlnae = 'ready'\n", "lnae"),
        ("[autopilot.limits]\ndisk = 1\n", "disk"),
        ("[autopilot.limits]\ncpu = 0\n", "cpu"),
        ("[autopilot.limits]\nsessions = 'two'\n", "sessions"),
        ("[autopilot.tier_weights]\nstandard = -1\n", "standard"),
        ("[autopilot]\nunsized_points = 0\n", "unsized_points"),
        ("[autopilot]\nidle_minutes = 0\n", "idle_minutes"),
        ("[autopilot]\nidle_minutes = 'soon'\n", "idle_minutes"),
        ("[autopilot]\nlane = ''\n", "lane"),
        ("[autopilot]\nreview_lane = 3\n", "review_lane"),
        ("autopilot = 3\n", "autopilot"),
    ],
)
def test_a_block_the_loop_cannot_run_from_is_refused_naming_the_key(tmp_path: Path, text: str, names: str) -> None:
    with pytest.raises(ConfigError, match=names):
        load(_write(tmp_path, text))
