"""The run ledger: each autopilot run's outcome, duration and resource peak, kept against its task."""

from pathlib import Path

from starpulse._internal.autopilot.ledger import Ledger, RunRecord


def _run(
    task: str = "TASK-1", tier: str = "standard", points: int = 8, cpu: float = 10, memory: float = 6
) -> RunRecord:
    return RunRecord(
        task, tier, points, "review", 120.0, {"cpu": cpu, "memory": memory, "sessions": 1, "review": points}
    )


def test_a_recorded_run_reads_back_against_its_task(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "runs.jsonl")
    first, other = _run("TASK-1"), _run("TASK-2")

    ledger.record(first)
    ledger.record(other)

    assert Ledger(tmp_path / "runs.jsonl").runs("TASK-1") == [first]  # a new ledger reads the file back


def test_a_missing_ledger_holds_no_runs(tmp_path: Path) -> None:
    assert Ledger(tmp_path / "runs.jsonl").runs() == []


def test_measured_demand_is_the_mean_peak_of_the_runs_of_that_tier_and_size(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "runs.jsonl")
    for cpu, memory in ((10, 4), (20, 6), (30, 8)):
        ledger.record(_run(cpu=cpu, memory=memory))
    ledger.record(_run(tier="deep", cpu=90))  # another tier: not counted
    ledger.record(_run(points=2, cpu=90))  # another size: not counted

    assert ledger.measured("standard", 8, min_runs=3) == {"cpu": 20, "memory": 6, "sessions": 1, "review": 8}


def test_too_few_runs_measure_nothing(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "runs.jsonl")
    ledger.record(_run())
    ledger.record(_run())

    assert ledger.measured("standard", 8, min_runs=3) is None
