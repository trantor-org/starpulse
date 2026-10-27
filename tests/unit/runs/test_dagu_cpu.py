"""The Dagu CPU share: the units' cgroup accounting, as a share of all the host's cores."""

from __future__ import annotations

from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.runs.dagu import CpuSampler, DaguRuns

CORES = 4


def account(root: Path, unit: str, usec: int) -> None:
    """Set `unit`'s cumulative CPU time, as the cgroup file reports it."""
    (root / unit).mkdir(exist_ok=True)
    (root / unit / "cpu.stat").write_text(f"usage_usec {usec}\nuser_usec {usec}\nsystem_usec 0\n")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def cgroups(tmp_path: Path) -> Path:
    return tmp_path


def sampler(root: Path, clock: Clock) -> CpuSampler:
    return CpuSampler(root, ("dagu*.service",), cores=CORES, clock=clock)


def test_the_first_reading_has_no_interval_to_divide_by(cgroups: Path) -> None:
    account(cgroups, "dagu.service", 5_000_000)

    assert sampler(cgroups, Clock())() is None


def test_the_share_counts_the_scheduler_and_every_worker_unit(cgroups: Path) -> None:
    clock = Clock()
    units = {"dagu.service": 0, "dagu-worker.service": 0, "dagu-worker-2.service": 0}
    for unit, usec in units.items():
        account(cgroups, unit, usec)
    read = sampler(cgroups, clock)
    read()

    clock.now += 10
    for unit, seconds in zip(units, (2, 6, 4), strict=True):
        account(cgroups, unit, seconds * 1_000_000)

    # 12 CPU-seconds in 10 s on 4 cores
    assert read() == {"share": 0.3, "cores": CORES}


def test_a_unit_outside_the_dagu_family_is_not_counted(cgroups: Path) -> None:
    clock = Clock()
    account(cgroups, "dagu.service", 0)
    account(cgroups, "docker.service", 0)
    read = sampler(cgroups, clock)
    read()

    clock.now += 10
    account(cgroups, "dagu.service", 4_000_000)
    account(cgroups, "docker.service", 40_000_000)

    assert read() == {"share": 0.1, "cores": CORES}


def test_a_unit_that_starts_between_readings_counts_what_it_has_used_and_one_that_ends_counts_nothing(
    cgroups: Path,
) -> None:
    clock = Clock()
    account(cgroups, "dagu.service", 0)
    account(cgroups, "dagu-cert-renew.service", 9_000_000)
    read = sampler(cgroups, clock)
    read()

    clock.now += 10
    (cgroups / "dagu-cert-renew.service" / "cpu.stat").unlink()
    (cgroups / "dagu-cert-renew.service").rmdir()
    account(cgroups, "dagu.service", 2_000_000)
    account(cgroups, "dagu-deferred-restart.service", 2_000_000)

    assert read() == {"share": 0.1, "cores": CORES}


def test_a_share_never_reads_above_all_the_cores_or_below_none(cgroups: Path) -> None:
    clock = Clock()
    account(cgroups, "dagu.service", 0)
    read = sampler(cgroups, clock)
    read()

    clock.now += 1
    account(cgroups, "dagu.service", 99_000_000)

    assert read() == {"share": 1.0, "cores": CORES}


def test_a_host_with_no_dagu_cgroup_reads_none(cgroups: Path) -> None:
    read = sampler(cgroups, Clock())
    read()

    assert read() is None


def test_the_page_gets_the_share_in_the_snapshot_and_in_the_delta_that_carries_it() -> None:
    feed = BoardFeed()
    readings = iter([{"share": 0.25, "cores": CORES}, {"share": 0.5, "cores": CORES}])
    runs = DaguRuns(feed.runs("ci"), lambda only=None: [], cpu=lambda: next(readings), instance="ci")
    runs.reconcile()
    _, changes = feed.subscribe()
    first = feed.snapshot()["cpu"]

    runs.reconcile()
    kind, payload = changes.get_nowait()

    assert first == {"ci": {"share": 0.25, "cores": CORES}}
    assert (kind, payload["cpu"]) == ("dags", {"ci": {"share": 0.5, "cores": CORES}})


def test_a_reading_that_is_none_keeps_the_last_share() -> None:
    feed = BoardFeed()
    readings = iter([{"share": 0.25, "cores": CORES}, None])
    runs = DaguRuns(feed.runs("ci"), lambda only=None: [], cpu=lambda: next(readings), instance="ci")
    runs.reconcile()
    runs.reconcile()

    assert feed.snapshot()["cpu"] == {"ci": {"share": 0.25, "cores": CORES}}
