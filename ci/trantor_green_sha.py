"""Print the newest trantor main commit whose CI passed, for the trantor-contract job to check out.

    <Validate check runs, reshaped by ci.yml's trantor-contract job> | python ci/trantor_green_sha.py

Reads a workflow-runs-shaped response on stdin: one entry per App `Validate` check run on trantor main's newest commits,
its commit as `head_sha`, its lowercased conclusion as `conclusion` and its completion time as `created_at`. Trantor's
tip can be red for a reason this package did not cause; checking it out ejected a starpulse merge-queue entry on every
red tip. The SHA goes to stdout and a log line naming it to stderr; a lookback with no green run exits non-zero with a
message.
"""

from __future__ import annotations

import json
import sys


def newest_green_sha(response: dict) -> str:
    green = [run for run in response.get("workflow_runs", []) if run.get("conclusion") == "success"]
    if not green:
        count = len(response.get("workflow_runs", []))
        raise SystemExit(f"no successful trantor main CI run among the newest {count}: nothing green to test against")
    newest = max(green, key=lambda run: run["created_at"])
    print(
        f"trantor-contract tests trantor main {newest['head_sha']} (CI green at {newest['created_at']})",
        file=sys.stderr,
    )
    return newest["head_sha"]


if __name__ == "__main__":
    print(newest_green_sha(json.load(sys.stdin)))
