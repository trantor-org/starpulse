"""The cell score: how well a profile did on the kind x size cell's completed tasks.

Per ADR "Randomized step-down trials", a task scores 40 clean completion, 20 mid-task operator prompts, 20 commits
after its PR was ready, 15 operator pass/fail rating and 5 time-to-merge; a part that is missing drops out and the rest
renormalize, and cost is excluded. Each part is 0-100: clean completion is 100 or 0, prompts and commits-after-ready
are `100 / (1 + count)`, time-to-merge halves each day (`100 * 0.5 ** (hours / 24)`). The rating arrives with its own
slice, so it is missing here, as is any GitHub part of a task with no merged pull request.

`pull_facts` reads the GitHub half: the commits a pull request took after it was marked ready for review, and the hours
from ready to merge.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from starpulse._internal.github_api import Transport, get
from starpulse._internal.level.cells import cell_of
from starpulse._internal.signals import CLAUDE_CODE

__all__ = ["PullFacts", "merged_pulls", "pull_facts", "score_cells", "task_score"]

WEIGHTS = {"clean": 40, "prompts": 20, "commits_after_ready": 20, "rating": 15, "time_to_merge": 5}


@dataclass(frozen=True)
class PullFacts:
    commits_after_ready: int
    hours_to_merge: float


def task_score(parts: Mapping[str, float | None]) -> float | None:
    """The weighted mean of the parts that are present, or None when none is."""
    held = {name: value for name, value in parts.items() if value is not None and name in WEIGHTS}
    total = sum(WEIGHTS[name] for name in held)
    return sum(WEIGHTS[name] * value for name, value in held.items()) / total if total else None


def _parts(slice_: Mapping[str, Any], facts: PullFacts | None) -> dict[str, float | None]:
    return {
        "clean": 100.0 if slice_["clean"] else 0.0,
        "prompts": 100 / (1 + slice_["operator_prompts"]),
        "commits_after_ready": None if facts is None else 100 / (1 + facts.commits_after_ready),
        "rating": None,
        "time_to_merge": None if facts is None else 100 * 0.5 ** (facts.hours_to_merge / 24),
    }


def _profile(slice_: Mapping[str, Any]) -> str:
    models, efforts = slice_["models"], slice_["efforts"]
    return f"{models[0] if models else 'unknown'}-{efforts[0] if efforts else 'unknown'}"


def score_cells(
    slices: Iterable[Mapping[str, Any]],
    tasks: Mapping[str, Mapping[str, Any]],
    facts: Mapping[str, PullFacts],
) -> list[dict[str, Any]]:
    """One row per kind x size cell and profile of the completed Claude Code slices, `{kind, size, profile, n,
    score}`, `score` the mean of the tasks' scores. `facts` maps a task to its merged pull request's facts."""
    scores: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    for s in slices:
        cell = cell_of(tasks, s["task"])
        if not s["complete"] or cell is None or set(s["harnesses"]) != {CLAUDE_CODE}:
            continue
        score = task_score(_parts(s, facts.get(s["task"])))
        if score is not None:
            scores[*cell, _profile(s)].append(score)
    return [
        {"kind": kind, "size": size, "profile": profile, "n": len(held), "score": sum(held) / len(held)}
        for (kind, size, profile), held in sorted(scores.items())
    ]


def _time(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def pull_facts(transport: Transport, repo: str, number: int) -> PullFacts | None:
    """The facts of merged pull request `number`: commits dated after it was last marked ready for review (all of
    them when it never was a draft) and hours from that moment to its merge. None while it is unmerged."""
    pull = get(transport, f"/repos/{repo}/pulls/{number}")
    if not pull.get("merged_at"):
        return None
    events = get(transport, f"/repos/{repo}/issues/{number}/events?per_page=100")["items"]
    readied = [e["created_at"] for e in events if e["event"] == "ready_for_review"]
    ready = _time(readied[-1] if readied else pull["created_at"])
    commits = get(transport, f"/repos/{repo}/pulls/{number}/commits?per_page=100")["items"]
    after = sum(_time(c["commit"]["committer"]["date"]) > ready for c in commits)
    return PullFacts(after, (_time(pull["merged_at"]) - ready).total_seconds() / 3600)


def merged_pulls(transport: Transport, repo: str, pages: int = 5) -> dict[str, int]:
    """Merged pull request number by the `TASK-N` its title names, from the `pages` most recently updated closed
    pages of 100; a task named by several keeps the newest."""
    found: dict[str, int] = {}
    for page in range(1, pages + 1):
        listed = get(transport, f"/repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=100&page={page}")
        for pull in listed["items"]:
            named = re.search(r"TASK-\d+", pull["title"])
            if named and pull.get("merged_at"):
                found.setdefault(named.group(), pull["number"])
        if len(listed["items"]) < 100:
            break
    return found
