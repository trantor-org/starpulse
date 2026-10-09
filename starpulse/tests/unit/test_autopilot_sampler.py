"""The 60 s sampler reads each capacity dimension and says when its headroom crosses its limit."""

from __future__ import annotations

import threading

from starpulse._internal.autopilot.sampler import Crossing, Reading, Sampler

LIMITS = {"cpu": 80.0, "memory": 80.0, "sessions": 2, "review": 20}


class Rig:
    """A sampler over stubs whose values the test sets."""

    def __init__(self) -> None:
        self.host = {"cpu": 10.0, "memory": 30.0}
        self.sessions = 0
        self.review = 0
        self.now = 1000.0
        self.crossings: list[Crossing] = []
        self.sampler = Sampler(
            LIMITS,
            probe=lambda: self.host,
            sessions=lambda: self.sessions,
            review=lambda: self.review,
            on_crossing=self.crossings.append,
            clock=lambda: self.now,
        )


def test_the_readings_carry_every_dimensions_use_and_limit() -> None:
    rig = Rig()
    rig.host = {"cpu": 42.5, "memory": 61.0}
    rig.sessions, rig.review = 1, 7

    assert rig.sampler.readings() == ([], None)  # nothing before the first sample

    rig.sampler.sample()

    readings, at = rig.sampler.readings()
    assert readings == [
        Reading("cpu", 42.5, 80.0),
        Reading("memory", 61.0, 80.0),
        Reading("sessions", 1, 2),
        Reading("review", 7, 20),
    ]
    assert at == 1000.0


def test_one_crossing_when_a_dimension_goes_from_under_its_limit_to_over_it() -> None:
    rig = Rig()
    rig.sampler.sample()  # the baseline: everything has headroom
    assert rig.crossings == []

    rig.host = {"cpu": 91.0, "memory": 30.0}
    rig.sampler.sample()

    assert rig.crossings == [Crossing("cpu", 91.0, 80.0, full=True)]


def test_no_event_while_a_dimension_stays_on_one_side_of_its_limit() -> None:
    rig = Rig()
    rig.sampler.sample()
    rig.host = {"cpu": 91.0, "memory": 30.0}
    rig.sampler.sample()
    rig.host = {"cpu": 99.0, "memory": 35.0}  # still over; the other is still under
    rig.sampler.sample()
    rig.sampler.sample()

    assert len(rig.crossings) == 1


def test_a_second_event_when_the_headroom_returns() -> None:
    rig = Rig()
    rig.sampler.sample()
    rig.sessions = 2  # at its limit: no headroom
    rig.sampler.sample()
    rig.sessions = 1
    rig.sampler.sample()

    assert rig.crossings == [Crossing("sessions", 2, 2, full=True), Crossing("sessions", 1, 2, full=False)]


def test_a_first_sample_over_a_limit_is_a_baseline_not_an_event() -> None:
    rig = Rig()
    rig.review = 25

    rig.sampler.sample()

    assert rig.crossings == []
    assert rig.sampler.readings()[0][3] == Reading("review", 25, 20)


def test_each_dimension_crosses_on_its_own() -> None:
    rig = Rig()
    rig.sampler.sample()
    rig.host = {"cpu": 85.0, "memory": 85.0}
    rig.review = 21
    rig.sampler.sample()

    assert [c.dimension for c in rig.crossings] == ["cpu", "memory", "review"]


def test_a_probe_that_fails_keeps_the_last_readings_and_the_next_sample_goes_on() -> None:
    rig = Rig()
    rig.sampler.sample()
    good = rig.sampler.readings()

    def broken() -> dict[str, float]:
        raise OSError("no /proc")

    rig.sampler._probe = broken
    rig.sampler.sample()

    assert rig.sampler.readings() == good
    assert rig.crossings == []


def test_run_forever_samples_until_stopped() -> None:
    rig = Rig()
    stop = threading.Event()
    calls = []

    def probe() -> dict[str, float]:
        calls.append(1)
        if len(calls) == 3:
            stop.set()
        return rig.host

    rig.sampler._probe = probe
    rig.sampler.run_forever(stop, interval=0)

    assert len(calls) == 3


def test_a_listener_that_raises_neither_stops_the_sampler_nor_hides_the_crossing_from_the_rest() -> None:
    rig = Rig()
    heard: list[str] = []

    def listener(crossing: Crossing) -> None:
        heard.append(crossing.dimension)
        raise RuntimeError("listener bug")

    rig.sampler._on_crossing = listener
    rig.sampler.sample()
    rig.host = {"cpu": 90.0, "memory": 90.0}
    rig.sampler.sample()  # must not raise

    assert heard == ["cpu", "memory"]
    assert rig.sampler.readings()[0][0].use == 90.0
