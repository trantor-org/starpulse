"""The one comment a pull request evicted from the merge queue gets, from recorded `dequeued` payloads."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from merge_queue_dequeue import MARKER, comment_on_dequeue

REPO = "trantor-org/starpulse"
PR = 555
QUEUE_SHA = "cad307e8e5a00c43d753d7898b4c25796dd18d69"
BOT = "github-actions[bot]"

#: `actions/runs?event=merge_group`, newest first: an older entry for the same PR, another PR's, then the
#: run that failed; the queue branch they name is already deleted.
RUNS = {
    "workflow_runs": [
        {
            "head_branch": "gh-readonly-queue/main/pr-777-aaaaaaa",
            "head_sha": "7" * 40,
            "created_at": "2026-10-17T00:20:00Z",
        },
        {
            "head_branch": "gh-readonly-queue/main/pr-555-bbbbbbb",
            "head_sha": QUEUE_SHA,
            "created_at": "2026-10-17T00:10:00Z",
        },
        {
            "head_branch": "gh-readonly-queue/main/pr-5555-ccccccc",
            "head_sha": "5" * 40,
            "created_at": "2026-10-17T00:09:00Z",
        },
        {
            "head_branch": "gh-readonly-queue/main/pr-555-ddddddd",
            "head_sha": "d" * 40,
            "created_at": "2026-10-17T00:00:00Z",
        },
    ]
}

#: `commits/<sha>/check-runs`: one failing App-posted required check, one cancelled, one green, one still running.
CHECK_RUNS = {
    "check_runs": [
        {"name": "python", "conclusion": "failure", "html_url": "https://github.com/x/y/runs/1"},
        {"name": "web", "conclusion": "success", "html_url": "https://github.com/x/y/runs/2"},
        {"name": "static-checks", "conclusion": "cancelled", "html_url": "https://github.com/x/y/runs/3"},
        {"name": "trantor-contract", "conclusion": None, "html_url": "https://github.com/x/y/runs/4"},
    ]
}


class FakeGh:
    """Answers the REST reads from recorded payloads and records every write."""

    def __init__(self, comments: list[dict[str, Any]] | None = None) -> None:
        self.comments = comments or []
        self.reads: list[str] = []
        self.writes: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> str:
        endpoint = next(a for a in args if a.startswith("repos/"))
        if "--method" in args:
            self.writes.append(
                (args[args.index("--method") + 1], endpoint, next(a for a in args if a.startswith("body=")))
            )
            return json.dumps({"html_url": "https://github.com/x/y/pull/555#issuecomment-9"})
        self.reads.append(endpoint)
        if "/actions/runs" in endpoint:
            return json.dumps(RUNS)
        if f"/commits/{QUEUE_SHA}/check-runs" in endpoint:
            return json.dumps([CHECK_RUNS])
        if endpoint.endswith("/comments"):
            return json.dumps([self.comments])
        raise AssertionError(f"unexpected read {endpoint}")


def _comment(gh: Callable[..., str], reason: str) -> str | None:
    return comment_on_dequeue(gh, REPO, PR, reason)


def test_failed_checks_links_each_failing_check_on_the_queue_commit() -> None:
    gh = FakeGh()
    _comment(gh, "failed_checks")
    ((verb, endpoint, body),) = gh.writes
    assert (verb, endpoint) == ("POST", f"repos/{REPO}/issues/{PR}/comments")
    assert body.startswith(f"body={MARKER}")
    assert "`failed_checks`" in body
    assert f"`{QUEUE_SHA[:7]}`" in body
    assert "[python](https://github.com/x/y/runs/1)" in body
    assert "[static-checks](https://github.com/x/y/runs/3)" in body
    assert "web" not in body
    assert "trantor-contract" not in body
    assert gh.reads[0].startswith(f"repos/{REPO}/actions/runs?event=merge_group")


def test_merge_conflict_names_the_reason_and_reads_no_checks() -> None:
    gh = FakeGh()
    _comment(gh, "merge_conflict")
    ((_, _, body),) = gh.writes
    assert "`merge_conflict`" in body
    assert "rebase" in body
    assert not any("check-runs" in read or "/actions/runs" in read for read in gh.reads)


def test_unknown_reason_is_named_verbatim() -> None:
    gh = FakeGh()
    _comment(gh, "queue_exploded")
    ((_, _, body),) = gh.writes
    assert body.startswith(f"body={MARKER}")
    assert "`queue_exploded`" in body
    assert "check-runs" not in "".join(gh.reads)


def test_a_repeat_eviction_updates_the_existing_comment() -> None:
    earlier = [
        {"id": 3, "user": {"login": "someone"}, "body": f"{MARKER}\nnot ours"},
        {"id": 4, "user": {"login": BOT}, "body": f"{MARKER}\n## old"},
    ]
    gh = FakeGh(earlier)
    _comment(gh, "failed_checks")
    ((verb, endpoint, _),) = gh.writes
    assert (verb, endpoint) == ("PATCH", f"repos/{REPO}/issues/comments/4")


def test_a_comment_the_app_posted_is_updated_not_duplicated() -> None:
    gh = FakeGh([{"id": 9, "user": {"login": "trantor-agent[bot]"}, "body": f"{MARKER}\n## old"}])
    _comment(gh, "failed_checks")
    ((verb, endpoint, _),) = gh.writes
    assert (verb, endpoint) == ("PATCH", f"repos/{REPO}/issues/comments/9")


def test_a_failed_checks_eviction_without_a_queue_run_says_so() -> None:
    class NoRuns(FakeGh):
        def __call__(self, *args: str) -> str:
            if any("/actions/runs" in a for a in args):
                return json.dumps({"workflow_runs": []})
            return super().__call__(*args)

    gh = NoRuns()
    _comment(gh, "failed_checks")
    ((_, _, body),) = gh.writes
    assert "no merge-queue run" in body


@pytest.mark.parametrize("reason", ["merged"])
def test_a_merge_posts_nothing(reason: str) -> None:
    gh = FakeGh()
    assert _comment(gh, reason) is None
    assert gh.writes == []
    assert gh.reads == []
