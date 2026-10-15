"""Parse a harness usage or credit limit and the wall clock at which it resets."""

from starpulse._internal.autopilot.usage_limit import until

# 10_000 s is 02:46:40 UTC on 1 January 1970; 21:00 UTC that day is 75_600 s.
NOW = 10_000.0
NINE_PM_UTC = 75_600.0


def test_a_weekly_limit_with_a_reset_clock_is_that_next_wall_time() -> None:
    assert until("You've hit your weekly limit · resets 9pm (UTC)", NOW) == NINE_PM_UTC


def test_a_usage_limit_with_no_reset_clock_pauses_for_five_hours() -> None:
    assert until("You have hit your usage limit", NOW) == NOW + 5 * 3600


def test_out_of_credits_is_a_limit() -> None:
    assert until("Claude was out of credits on both accounts", NOW) == NOW + 5 * 3600


def test_other_errors_are_not_a_limit() -> None:
    assert until("tmux could not start starpulse-T-1: exit 1", NOW) is None
