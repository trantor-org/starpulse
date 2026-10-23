"""The `[scheduler]` block: every default the ADR's decision 6 names works with no block, and each can be overridden."""

from pathlib import Path

import pytest

from starpulse._internal.scheduler.probe import LocalProbe
from starpulse._internal.config.scheduler import DIMENSIONS, Scheduler
from starpulse._internal.config.config import ConfigError, load


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return path


def test_no_block_resolves_every_default_but_the_starter(tmp_path: Path) -> None:
    for config in (load(None), load(_write(tmp_path, ""))):
        scheduler = config.scheduler

        assert scheduler == Scheduler()
        assert scheduler.eligible_lane("to_do") == "to_do"  # the board's initial lane
        assert scheduler.tier_weights == {"fast": 1, "standard": 2, "deep": 4}
        assert scheduler.unsized_points == 3
        assert scheduler.reviewed_lane("pr") == "pr"  # the board's review lane
        assert scheduler.idle_minutes == 30
        assert scheduler.state_dir is None  # the switch and the ledger sit beside the config
        assert set(scheduler.limits) == set(DIMENSIONS) == {"cpu", "memory", "sessions", "review"}
        assert all(limit > 0 for limit in scheduler.limits.values())
    assert callable(LocalProbe())  # the local CPU and memory probe is the sampler's default


def test_a_block_overrides_each_default(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[scheduler]
lane = "ready"
review_lane = "qa"
unsized_points = 5
idle_minutes = 10
state_dir = "starpulse-state"

[scheduler.tier_weights]
standard = 3

[scheduler.limits]
sessions = 4
review = 30
""",
    )

    scheduler = load(path).scheduler

    assert scheduler.eligible_lane("to_do") == "ready"
    assert scheduler.review_lane == "qa"
    assert scheduler.unsized_points == 5
    assert scheduler.idle_minutes == 10
    assert scheduler.state_dir == "starpulse-state"
    assert scheduler.tier_weights == {"fast": 1, "standard": 3, "deep": 4}
    assert scheduler.limits["sessions"] == 4 and scheduler.limits["review"] == 30
    assert scheduler.limits["cpu"] == Scheduler().limits["cpu"]  # a limit left out keeps its default


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("[scheduler]\nlnae = 'ready'\n", "lnae"),
        ("[scheduler.limits]\ndisk = 1\n", "disk"),
        ("[scheduler.limits]\ncpu = 0\n", "cpu"),
        ("[scheduler.limits]\nsessions = 'two'\n", "sessions"),
        ("[scheduler.tier_weights]\nstandard = -1\n", "standard"),
        ("[scheduler.priority_matrix]\n'huge/low' = 2\n", "huge/low"),
        ("[scheduler.priority_matrix]\n'high/high' = 0\n", "high/high"),
        ("[scheduler]\nunsized_points = 0\n", "unsized_points"),
        ("[scheduler]\nidle_minutes = 0\n", "idle_minutes"),
        ("[scheduler]\nidle_minutes = 'soon'\n", "idle_minutes"),
        ("[scheduler]\nlane = ''\n", "lane"),
        ("[scheduler]\nreview_lane = 3\n", "review_lane"),
        ("[scheduler]\nstate_dir = ''\n", "state_dir"),
        ("[scheduler]\nstate_dir = 3\n", "state_dir"),
        ("scheduler = 3\n", "scheduler"),
    ],
)
def test_a_block_the_loop_cannot_run_from_is_refused_naming_the_key(tmp_path: Path, text: str, names: str) -> None:
    with pytest.raises(ConfigError, match=names):
        load(_write(tmp_path, text))


def test_the_priority_matrix_states_its_default_weight_and_a_block_overrides_a_cell(tmp_path: Path) -> None:
    default = load(None).scheduler
    override = load(_write(tmp_path, "[scheduler.priority_matrix]\n'high/high' = 20\ndefault = 5\n")).scheduler

    assert default.priority_matrix["default"] == 4.0
    assert default.priority_of({"impact": "low", "urgency": "low"}) == ("low/low", 1.0)
    assert default.priority_of({"impact": "high", "urgency": "high"}) == ("high/high", 9.0)
    assert default.priority_of({"impact": "", "urgency": ""}) == ("default", 4.0)  # no Impact or Urgency
    assert default.priority_of({"impact": "high"}) == ("default", 4.0)  # a half-set Task has no cell
    assert override.priority_of({"impact": "high", "urgency": "high"}) == ("high/high", 20.0)
    assert override.priority_of({}) == ("default", 5.0)
    assert override.priority_of({"impact": "low", "urgency": "low"}) == ("low/low", 1.0)  # a cell left out keeps its weight
