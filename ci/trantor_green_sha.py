"""Print the newest trantor main commit whose CI passed, for the trantor-contract job to check out.

    gh api "repos/trantor-org/trantor/actions/workflows/ci.yml/runs?branch=main&event=push&per_page=30" \\
        | python ci/trantor_green_sha.py

Reads the workflow-runs response on stdin. Trantor's tip can be red for a reason this package did not cause; checking it
out ejected a starpulse merge-queue entry on every red tip. The SHA goes to stdout and a log line naming it to stderr; a
lookback with no green push run exits non-zero with a message.
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
