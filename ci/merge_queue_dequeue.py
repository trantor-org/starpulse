"""Comment the reason and the failing checks on a pull request evicted from the merge queue.

GitHub shows an eviction as one "removed from the merge queue" timeline line and deletes the `gh-readonly-queue/*`
branch after the run. This keeps one comment per pull request, rewritten in place on a repeat eviction, naming the
`dequeued` payload's `reason` and, for `failed_checks`, linking each failing check run on the queue commit. The
commit is the head_sha of the pull request's latest `merge_group` Actions run, which outlives the branch.

`gh` authenticates with the environment's `GH_TOKEN`, so the caller picks who posts the comment. Run by this
repository's `merge-queue-dequeue.yml` workflow.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from typing import Any

#: The comment's first line; the only thing that makes a comment this script's.
MARKER = "<!-- trantor:merge-queue-dequeue -->"
#: Who posts it: the Actions token's bot, or the workspace App that runs the same script from the operator's workspace.
AUTHORS = frozenset({"github-actions[bot]", "trantor-agent[bot]"})

#: The `reason` of the timeline's removal event, which the `dequeued` payload repeats. GitHub documents it as a free
#: string; these are the values seen on trantor-org/starpulse evictions.
REASONS = {
    "failed_checks": "a required check failed on the merge-queue commit",
    "merge_conflict": "the branch conflicts with the queue's base; rebase it on main",
    "manual": "someone removed it from the queue",
}
#: The reasons that carry a queue commit whose checks are worth listing.
CHECK_REASONS = frozenset({"failed_checks"})
#: A merged pull request is dequeued too, with this reason: nothing to report.
SILENT_REASONS = frozenset({"merged"})
#: Check-run conclusions that held the queue back.
FAILING = frozenset({"failure", "timed_out", "cancelled", "action_required", "startup_failure"})


def queue_commit(runs: Sequence[Mapping[str, Any]], pr: int) -> str | None:
    """The head_sha of the pull request's newest `merge_group` run, found by its `pr-<N>-` queue branch."""
    branch = re.compile(rf"^gh-readonly-queue/[^/]+/pr-{pr}-")
    mine = [r for r in runs if branch.match(r["head_branch"])]
    return max(mine, key=lambda r: r["created_at"])["head_sha"] if mine else None


def failing_checks(check_runs: Sequence[Mapping[str, Any]]) -> list[str]:
    """One markdown bullet per check run that failed, timed out or was cancelled."""
    return [f"- [{c['name']}]({c['html_url']}) — {c['conclusion']}" for c in check_runs if c["conclusion"] in FAILING]


def earlier_comment(comments: Sequence[Mapping[str, Any]]) -> int | None:
    """The id of this script's earlier comment on the pull request, if it left one."""
    for comment in comments:
        if comment["user"]["login"] in AUTHORS and comment["body"].startswith(MARKER):
            return comment["id"]
    return None


def comment_body(reason: str, sha: str | None, checks: Sequence[str]) -> str:
    lines = [
        MARKER,
        "## Removed from the merge queue",
        "",
        f"Reason: `{reason}`" + (f" — {REASONS[reason]}." if reason in REASONS else "."),
    ]
    if reason in CHECK_REASONS and sha is None:
        lines += ["", "Found no merge-queue run for this pull request, so the failing checks are unknown."]
    elif sha is not None:
        lines += [
            "",
            f"Failing checks on queue commit `{sha[:7]}`:",
            *(checks or ["- none failing now; a rerun may have passed"]),
        ]
    return "\n".join(lines)


def comment_on_dequeue(gh: Callable[..., str], repo: str, pr: int, reason: str) -> str | None:
    """Create or rewrite the pull request's one dequeue comment; returns its URL, or None when nothing is owed."""
    if reason in SILENT_REASONS:
        return None
    sha, checks = None, []
    if reason in CHECK_REASONS:
        runs = json.loads(gh("api", f"repos/{repo}/actions/runs?event=merge_group&per_page=100"))["workflow_runs"]
        sha = queue_commit(runs, pr)
    if sha is not None:
        pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/commits/{sha}/check-runs?per_page=100"))
        checks = failing_checks([c for page in pages for c in page["check_runs"]])
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/issues/{pr}/comments"))
    earlier = earlier_comment([c for page in pages for c in page])
    body = f"body={comment_body(reason, sha, checks)}"
    if earlier is None:
        return json.loads(gh("api", "--method", "POST", f"repos/{repo}/issues/{pr}/comments", "-f", body))["html_url"]
    return json.loads(gh("api", "--method", "PATCH", f"repos/{repo}/issues/comments/{earlier}", "-f", body))["html_url"]


def _gh(*args: str) -> str:  # pragma: no cover  # pragma: no mutate block — process boundary
    done = subprocess.run(("gh", *args), check=False, capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise RuntimeError(f"`gh {' '.join(args[:3])}` exited {done.returncode}: {done.stderr.strip()}")
    return done.stdout


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover  # pragma: no mutate block — CLI wiring
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--reason", required=True, help="the `reason` of the pull_request dequeued payload")
    args = parser.parse_args(argv)
    print(comment_on_dequeue(_gh, args.repo, args.pr, args.reason) or "no comment owed")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
