"""Record which source files each test executes during the nightly full suite, and publish the map for the select step.

The nightly shards run pytest with `--cov-context=test`; each writes a coverage data file, and the `coverage-map` job
combines them. `build` turns the combined file into `{"sha", "collected", "tests": {node id: [source files]}}`, the
files relative to the checkout, a test's setup, call and teardown merged. `publish` writes it as `<sha>.json` plus
`latest.json` in `--out` (default: a directory in the CI runner user's cache, where the `ci-sp-python` select step
reads it). `latest` prints the newest map's sha and how many of the collected tests it covers.

  build DATA --sha SHA --collected FILE [--root DIR] [--out DIR]   write the map of the combined coverage file DATA
  latest [--out DIR]                                            print the newest published map: sha, tests, share
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

#: Where the CI runner host keeps the maps; the nightly's runner and the `ci-sp-python` DAG both run as the same user.
DEFAULT_DIR = Path(
    os.environ.get("STARPULSE_COVERAGE_MAP_DIR") or Path.home() / ".cache" / "starpulse-ci" / "coverage-map"
)
LATEST = "latest.json"

#: The share of collected tests a map must name to be published: a red nightly's shards still upload their coverage data,
#: so a shard that crashed outright (no data) must not leave a map every pull request's selection trusts.
MIN_RATIO = 0.9


def build(data_file: Path, root: Path, *, sha: str, collected: list[str]) -> dict:
    """The map of the combined coverage file for the `collected` node ids: each test's sorted source files under `root`.

    A parametrized case that left no context of its own (its sibling's run covered the same lines) takes its function's
    files; a test with no files at all is left out, which `ratio` counts against the map.
    """
    import coverage  # noqa: PLC0415  only the nightly's `build` has it; `ci/select_tests.py` imports `latest` from a bare env

    data = coverage.CoverageData(str(data_file))
    data.read()
    ran: dict[str, set[str]] = {}
    for path in data.measured_files():
        # `relative_files` makes shard data portable across runners; an absolute path outside `root` is not ours.
        measured = Path(path)
        if measured.is_absolute() and not measured.is_relative_to(root):
            continue
        relative = measured.relative_to(root).as_posix() if measured.is_absolute() else measured.as_posix()
        for labels in data.contexts_by_lineno(path).values():
            for label in labels:
                nodeid = label.partition("|")[0]
                if nodeid:
                    ran.setdefault(nodeid, set()).add(relative)
    by_function: dict[str, set[str]] = {}
    for nodeid, files in ran.items():
        by_function.setdefault(nodeid.partition("[")[0], set()).update(files)
    tests = {}
    for nodeid in sorted(collected):
        files = ran.get(nodeid) or by_function.get(nodeid.partition("[")[0])
        if files:
            tests[nodeid] = sorted(files)
    return {"sha": sha, "collected": len(collected), "tests": tests}


def ratio(coverage_map: dict) -> float:
    """The share of collected tests the map names."""
    return len(coverage_map["tests"]) / coverage_map["collected"]


def publish(coverage_map: dict, directory: Path) -> None:
    """Write `<sha>.json` and replace `latest.json` atomically, so a reader never sees half a map."""
    directory.mkdir(parents=True, exist_ok=True)
    text = json.dumps(coverage_map, separators=(",", ":"))
    (directory / f"{coverage_map['sha']}.json").write_text(text)
    staged = directory / f".{LATEST}.tmp"
    staged.write_text(text)
    staged.replace(directory / LATEST)


def latest(directory: Path) -> dict | None:
    """The newest published map, or None before the first nightly published one."""
    path = directory / LATEST
    return json.loads(path.read_text()) if path.exists() else None


def renamed_since(root: Path, sha: str) -> dict[str, str]:
    """Old path -> new path for the files git sees renamed between `sha` and HEAD; empty when git cannot tell."""
    diff = subprocess.run(
        ["git", "-C", str(root), "diff", "-M", "--name-status", sha, "HEAD"], capture_output=True, text=True
    )
    rows = [line.split("\t") for line in diff.stdout.splitlines()] if diff.returncode == 0 else []
    return {row[1]: row[2] for row in rows if row[0].startswith("R") and len(row) == 3}


def facts(coverage_map: dict, directory: Path, root: Path, *, now: float | None = None) -> dict:
    """What a run's selection leaned on: the map's sha, its hours since publishing, and how many of the source files it
    names the checkout at `root` lost without a rename (a module that moved keeps its tests; one deleted does not)."""
    named = {file for files in coverage_map["tests"].values() for file in files}
    age = (now or time.time()) - (directory / LATEST).stat().st_mtime
    moved = renamed_since(root, coverage_map["sha"])
    missing = sum(not (root / moved.get(file, file)).is_file() for file in named)
    return {"sha": coverage_map["sha"], "age_hours": round(age / 3600, 1), "files": len(named), "missing": missing}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    built = commands.add_parser("build")
    built.add_argument("data", type=Path)
    built.add_argument("--sha", required=True)
    built.add_argument("--collected", type=Path, required=True, help="file of the collected node ids, one per line")
    built.add_argument("--root", type=Path, default=Path.cwd())
    commands.add_parser("latest")
    for sub in commands.choices.values():
        sub.add_argument("--out", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args(argv)
    if args.command == "build":
        built_map = build(
            args.data, args.root.resolve(), sha=args.sha, collected=args.collected.read_text().splitlines()
        )
        if ratio(built_map) < MIN_RATIO:
            share = f"{ratio(built_map):.1%} of the collected tests, under {MIN_RATIO:.0%}"
            print(f"the map names {share}: not published", file=sys.stderr)
            return 1
        publish(built_map, args.out)
        print(f"{built_map['sha']} {len(built_map['tests'])}/{built_map['collected']} tests {ratio(built_map):.1%}")
        return 0
    newest = latest(args.out)
    if newest is None:
        print(f"no coverage map in {args.out}", file=sys.stderr)
        return 1
    print(f"{newest['sha']} {len(newest['tests'])}/{newest['collected']} tests {ratio(newest):.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
