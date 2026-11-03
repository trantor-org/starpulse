"""One sweeper pass: the kinds in order, then the housekeeping, each kind's counts kept as metrics and one journal line."""

from __future__ import annotations

import logging

import pytest
from starpulse.sweeper.passes import Metrics, Outcome, run_pass


class _Kind:
    def __init__(self, name: str, outcome: Outcome | Exception, order: list[str]) -> None:
        self.name = name
        self._outcome = outcome
        self._order = order

    def run(self) -> Outcome:
        self._order.append(self.name)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _Housekeeping:
    def __init__(self, name: str, order: list[str], fails: bool = False) -> None:
        self.name = name
        self._order = order
        self._fails = fails

    def run(self) -> None:
        self._order.append(self.name)
        if self._fails:
            raise OSError("archive is full")


def _value(text: str, series: str) -> float:
    lines = [line for line in text.splitlines() if line.startswith(series + " ")]
    assert lines, f"{series} is not exported:\n{text}"
    return float(lines[0].rsplit(" ", 1)[1])


def test_a_pass_runs_the_kinds_in_order_and_then_the_housekeeping() -> None:
    order: list[str] = []
    kinds = [_Kind("readers", Outcome(), order), _Kind("board-files", Outcome(), order)]
    metrics = Metrics([k.name for k in kinds])

    run_pass(kinds, [_Housekeeping("event-log-prune", order)], metrics)

    assert order == ["readers", "board-files", "event-log-prune"]


def test_a_pass_counts_corrections_and_samples_by_kind_and_the_pass_itself() -> None:
    order: list[str] = []
    kinds = [_Kind("readers", Outcome(corrected=2, sampled=5), order), _Kind("claims", Outcome(sampled=1), order)]
    metrics = Metrics([k.name for k in kinds])

    run_pass(kinds, [], metrics, clock=lambda: 1234.0)
    run_pass(kinds, [], metrics, clock=lambda: 1300.0)
    text = metrics.exposition()

    assert _value(text, "starpulse_sweeper_passes_total") == 2
    assert _value(text, "starpulse_sweeper_last_pass_timestamp_seconds") == 1300
    assert _value(text, 'starpulse_sweeper_corrections_total{kind="readers"}') == 4
    assert _value(text, 'starpulse_sweeper_samples_total{kind="readers"}') == 10
    assert _value(text, 'starpulse_sweeper_corrections_total{kind="claims"}') == 0
    assert _value(text, 'starpulse_sweeper_pass_errors_total{kind="claims"}') == 0


def test_a_kind_that_raises_is_counted_as_an_error_and_the_other_kinds_still_run() -> None:
    order: list[str] = []
    kinds = [_Kind("readers", RuntimeError("boom"), order), _Kind("claims", Outcome(corrected=1), order)]
    metrics = Metrics([k.name for k in kinds])

    run_pass(kinds, [_Housekeeping("event-log-prune", order)], metrics)
    text = metrics.exposition()

    assert order == ["readers", "claims", "event-log-prune"]
    assert _value(text, 'starpulse_sweeper_pass_errors_total{kind="readers"}') == 1
    assert _value(text, 'starpulse_sweeper_corrections_total{kind="claims"}') == 1
    assert _value(text, "starpulse_sweeper_passes_total") == 1


def test_a_housekeeping_step_that_raises_is_an_error_and_the_next_step_still_runs() -> None:
    order: list[str] = []
    steps = [_Housekeeping("event-log-prune", order, fails=True), _Housekeeping("lint", order)]
    metrics = Metrics([])

    run_pass([], steps, metrics)

    assert order == ["event-log-prune", "lint"]
    assert _value(metrics.exposition(), 'starpulse_sweeper_pass_errors_total{kind="housekeeping:event-log-prune"}') == 1


def test_a_pass_writes_one_journal_line_naming_each_kind_and_its_corrections(caplog: pytest.LogCaptureFixture) -> None:
    order: list[str] = []
    kinds = [_Kind("readers", Outcome(corrected=3, sampled=9), order), _Kind("claims", RuntimeError("x"), order)]

    with caplog.at_level(logging.INFO, logger="starpulse.sweeper.passes"):
        run_pass(kinds, [], Metrics([k.name for k in kinds]))

    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert lines == ["sweeper: pass 1: readers=3 claims=error"]
