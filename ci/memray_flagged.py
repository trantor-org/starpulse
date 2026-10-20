"""Rerun exactly the tests ci/slow_tests.py flagged under `pytest --memray`: `python ci/memray_flagged.py REPORT OUT_DIR`.

Each test runs alone, so one that fails or vanishes cannot take the others' stats with it. OUT_DIR gets `N.txt`, pytest's
output with memray's allocation report for the Nth test, and `stats.json`, `{"tests": [{"nodeid", "stats"}]}` where `stats` is
that file's name, or null when the rerun left no memray report; each such test is also a `::warning` line. The exit status
stays 0: the suite's own result is the run's, and a missing report is named, not failed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

#: Absent from the rerun's environment: xdist workers (memray does not profile them), the shard split (the ids are already
#: this shard's) and the screen itself (it would overwrite the report being read).
DROPPED = ("PYTEST_ADDOPTS", "SHARD_COUNT", "SHARD_INDEX", "TEST_COST_REPORT")


def rerun(nodeid: str, out: Path, number: int) -> str | None:
    """The name of the file holding `nodeid`'s memray report, or None when the rerun left none."""
    env = {key: value for key, value in os.environ.items() if key not in DROPPED}
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--memray",
            f"--memray-bin-path={out / str(number)}",
            "-p",
            "no:cacheprovider",
            nodeid,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    (out / f"{number}.txt").write_text(done.stdout + done.stderr)
    return f"{number}.txt" if "Allocation results for" in done.stdout else None


def main(report: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    nodeids = [row["nodeid"] for row in json.loads(report.read_text())["tests"]]
    stats = [{"nodeid": nodeid, "stats": rerun(nodeid, out, number)} for number, nodeid in enumerate(nodeids, 1)]
    (out / "stats.json").write_text(json.dumps({"tests": stats}, indent=2))
    for row in stats:
        if row["stats"] is None:
            print(f"::warning title=No memray stats::{row['nodeid']}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
