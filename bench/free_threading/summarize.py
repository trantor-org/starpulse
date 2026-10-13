"""Print one row per route and run from a `run.sh` results directory: p50, p95 and max in ms, then requests a second,
with each run's host load and whether its server last reported a GIL.

    python3 bench/free_threading/summarize.py <out-dir>
"""

import csv
import sys
from pathlib import Path


def runs(out: Path) -> list[str]:
    """The run names (`gil-1`, `ft-1`, ...) in the order they ran."""
    stats = sorted(out.glob("*_stats.csv"), key=lambda path: path.stat().st_mtime)
    return [path.name.removesuffix("_stats.csv") for path in stats]


def gil(log: Path) -> str:
    """The server's last `gil_enabled=` report, or `?` when it made none."""
    reports = [line.strip() for line in log.read_text().splitlines() if line.startswith("gil_enabled=")]
    return reports[-1].removeprefix("gil_enabled=") if reports else "?"


def main(out: Path) -> None:
    names = runs(out)
    for name in names:
        load = (out / f"{name}.load").read_text().split()
        print(f"{name}: gil_enabled={gil(out / f'{name}.server.log')} load1 before/after {load[0]}/{load[5]}")
    print(f"{'route':48} {'run':6} {'reqs':>6} {'p50':>7} {'p95':>7} {'max':>8} {'rps':>6}")
    rows = {name: list(csv.DictReader((out / f"{name}_stats.csv").open())) for name in names}
    routes = sorted({row["Name"] for table in rows.values() for row in table}, key=lambda n: (n == "Aggregated", n))
    for route in routes:
        for name in names:
            row = next((row for row in rows[name] if row["Name"] == route), None)
            if row is None:
                continue
            print(
                f"{route[:48]:48} {name:6} {row['Request Count']:>6} {row['50%']:>7} {row['95%']:>7}"
                f" {float(row['Max Response Time']):>8.0f} {float(row['Requests/s']):>6.1f}"
            )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
