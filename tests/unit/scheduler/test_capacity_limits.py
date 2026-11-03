"""The cpu and memory limits an operator sets in Admin override `starpulse.toml`: kept in the history store, read on
every sampler and admission pass, and gone once cleared."""

from pathlib import Path

import pytest
from starpulse.event_log.event_log import EventLog
from starpulse.scheduler.model.capacity_limits import CapacityLimitSetting
from starpulse.scheduler.model.config import Scheduler
from starpulse.scheduler.model.sampler import Sampler


def _log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")


def test_no_limit_is_set_until_an_operator_sets_one(tmp_path: Path) -> None:
    limits = CapacityLimitSetting(_log(tmp_path))

    assert (limits.get("cpu"), limits.get("memory")) == (None, None)


def test_limits_are_kept_per_dimension_and_survive_a_restart(tmp_path: Path) -> None:
    CapacityLimitSetting(_log(tmp_path)).set({"cpu": 95, "memory": 70.5})

    restarted = CapacityLimitSetting(_log(tmp_path))
    assert (restarted.get("cpu"), restarted.get("memory")) == (95, 70.5)


def test_none_clears_only_that_dimension(tmp_path: Path) -> None:
    limits = CapacityLimitSetting(_log(tmp_path))
    limits.set({"cpu": 95, "memory": 70})

    limits.set({"cpu": None})

    assert (limits.get("cpu"), limits.get("memory")) == (None, 70)


@pytest.mark.parametrize("value", [0, -1, 100.5, 101, "90", True, [3], float("nan")])
def test_a_limit_outside_zero_to_a_hundred_percent_raises_and_changes_nothing(tmp_path: Path, value: object) -> None:
    limits = CapacityLimitSetting(_log(tmp_path))
    limits.set({"cpu": 85, "memory": 75})

    with pytest.raises(ValueError, match="cpu limit"):
        limits.set({"memory": 60, "cpu": value})

    assert (limits.get("cpu"), limits.get("memory")) == (85, 75)


def test_a_dimension_that_is_not_cpu_or_memory_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sessions"):
        CapacityLimitSetting(_log(tmp_path)).set({"sessions": 5})


def test_an_unreadable_stored_value_is_no_override(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.set_setting("scheduler.capacity_limits", "garbage")

    assert CapacityLimitSetting(log).get("cpu") is None


def test_the_policy_reads_the_override_on_every_call_and_falls_back_to_the_config(tmp_path: Path) -> None:
    stored = CapacityLimitSetting(_log(tmp_path))
    policy = Scheduler(limits={**Scheduler().limits, "cpu": 90, "memory": 85}).with_overrides(
        lambda harness: None, stored.get
    )

    assert policy.capacity_limit("cpu") == {"limit": 90, "source": "starpulse.toml", "configLimit": 90}
    assert policy.effective_limits()["memory"] == 85

    stored.set({"cpu": 97})

    assert policy.capacity_limit("cpu") == {"limit": 97, "source": "admin", "configLimit": 90}
    assert policy.effective_limits() == {**policy.limits, "cpu": 97}

    stored.set({"cpu": None})

    assert policy.limit("cpu") == 90


def test_the_sampler_judges_a_reading_against_the_limit_as_it_is_now() -> None:
    limits = {"cpu": 90.0, "memory": 85.0, "sessions": 2.0, "review": 20.0}
    crossings: list[object] = []
    sampler = Sampler(
        lambda: limits,
        lambda: {"cpu": 95.8, "memory": 10.0},
        sessions=lambda: 0.0,
        review=lambda: 0.0,
        on_crossing=crossings.append,
        clock=lambda: 1.0,
    )
    sampler.sample()
    assert {r.name: r.full for r in sampler.readings()[0]}["cpu"] is True

    limits["cpu"] = 99.0

    assert {r.name: (r.limit, r.full) for r in sampler.readings()[0]}["cpu"] == (99.0, False)
    sampler.sample()
    assert [c.dimension for c in crossings if not c.full] == ["cpu"]  # type: ignore[attr-defined]
