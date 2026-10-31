"""The session cap an operator sets in Admin overrides `starpulse.toml`: kept per harness in the history store, read on
every admission pass, and gone once cleared."""

from pathlib import Path

import pytest
from starpulse.event_log.event_log import EventLog
from starpulse.scheduler.model.config import Scheduler
from starpulse.scheduler.model.session_caps import SessionCapSetting


def _log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")


def test_no_cap_is_set_until_an_operator_sets_one(tmp_path: Path) -> None:
    assert SessionCapSetting(_log(tmp_path)).get("claude") is None


def test_a_cap_is_kept_per_harness_and_survives_a_restart(tmp_path: Path) -> None:
    SessionCapSetting(_log(tmp_path)).set("claude", 12)

    restarted = SessionCapSetting(_log(tmp_path))
    assert restarted.get("claude") == 12
    assert restarted.get("cursor") is None


def test_none_clears_only_that_harness(tmp_path: Path) -> None:
    caps = SessionCapSetting(_log(tmp_path))
    caps.set("claude", 12)
    caps.set("cursor", 3)

    caps.set("claude", None)

    assert (caps.get("claude"), caps.get("cursor")) == (None, 3)


@pytest.mark.parametrize("value", [0, -1, 2.5, "7", True, [3]])
def test_a_cap_that_is_not_a_positive_integer_raises_and_changes_nothing(tmp_path: Path, value: object) -> None:
    caps = SessionCapSetting(_log(tmp_path))
    caps.set("claude", 9)

    with pytest.raises(ValueError, match="session cap"):
        caps.set("claude", value)

    assert caps.get("claude") == 9


def test_an_unreadable_stored_value_is_no_override(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.set_setting("scheduler.session_caps", "garbage")

    assert SessionCapSetting(log).get("claude") is None


def test_the_policy_reads_the_override_on_every_call_and_falls_back_to_the_config(tmp_path: Path) -> None:
    caps = SessionCapSetting(_log(tmp_path))
    policy = Scheduler(limits={**Scheduler().limits, "sessions": 30}, session_limits={"cursor": 4}).with_overrides(
        caps.get
    )

    assert (policy.session_limit("claude"), policy.session_limit("cursor")) == (30, 4)
    assert policy.session_cap("claude") == {"harness": "claude", "limit": 30, "source": "starpulse.toml", "configLimit": 30}

    caps.set("claude", 50)
    caps.set("cursor", 6)

    assert (policy.session_limit("claude"), policy.session_limit("cursor")) == (50, 6)
    assert policy.session_cap("cursor") == {"harness": "cursor", "limit": 6, "source": "admin", "configLimit": 4}

    caps.set("claude", None)

    assert policy.session_limit("claude") == 30
