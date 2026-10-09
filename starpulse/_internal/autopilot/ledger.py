"""The run ledger: each autopilot run's outcome, duration and resource peak, kept against its task.

It is the labelled data the admission rule learns demand from and an optional predictor trains on. One JSON line per run,
in a file beside the toggle, so a restart keeps it and a fresh install needs no store.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

#: Where the ledger lives, in the directory of the `--config` file, beside the toggle.
LEDGER_FILE = "starpulse-autopilot-runs.jsonl"


@dataclass(frozen=True)
class RunRecord:
    """One finished run: the lane its task ended in (`outcome`), how long it ran, and the demand it drew at its highest.

    `peak` is that demand per capacity dimension in the dimension's own unit, the shape of a task's demand vector.
    """

    task: str
    tier: str
    points: int
    outcome: str
    duration_s: float
    peak: Mapping[str, float]


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, run: RunRecord) -> None:
        """Append `run`; a line is one write, so a reader sees a whole run or none of it."""
        with self.path.open("a") as file:
            file.write(json.dumps(asdict(run)) + "\n")

    def runs(self, task: str | None = None) -> list[RunRecord]:
        """Every recorded run, oldest first, or only `task`'s; none while no file exists."""
        try:
            lines = self.path.read_text().splitlines()
        except FileNotFoundError:
            return []
        runs = [RunRecord(**json.loads(line)) for line in lines]
        return [run for run in runs if task is None or run.task == task]

    def measured(self, tier: str, points: int, min_runs: int) -> dict[str, float] | None:
        """The mean peak of the runs of `tier` and `points`, or None while fewer than `min_runs` exist."""
        peaks = [run.peak for run in self.runs() if (run.tier, run.points) == (tier, points)]
        if not peaks or len(peaks) < min_runs:
            return None
        return {name: sum(peak[name] for peak in peaks) / len(peaks) for name in peaks[0]}
