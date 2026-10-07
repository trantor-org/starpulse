"""The Ledger: each Board transition's occurrences paired with the workflow runs they caused.

A workflow is tied to a Board event, either because the machine's YAML says the event cues it or because it writes the
event. An *occurrence* is one time the event happened: for the merge event a pull request landing (its merge commit,
pull request and tasks), for any other event a task entering the lane the event reaches. A run pairs with an occurrence
two ways:

- by key, when the runs instance's `[runs.commit]` names a run parameter that carries the occurrence's commit
  (`after`) or task (`task`) and the run has it; the pairing is certain;
- by time, otherwise: the newest occurrence before the run started. The pairing is marked `inferred`, and
  `ambiguous` counts the older occurrences that landed since the workflow's previous run started, any of which the
  run may equally be for.

A run that carries the key but names no occurrence we hold pairs with nothing; time never overrides a key.
Pairing is per workflow, so one occurrence can hold a run of each tied workflow. A rerun of an occurrence replaces
its earlier run, and a keyed run outranks an inferred one. Among inferred runs the earliest after the occurrence
wins, since a later one more likely answers a later trigger.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from starpulse.config import CommitKeys

__all__ = ["MERGE_EVENT", "Occurrence", "build", "pair", "pull_occurrences"]

#: The Board event whose occurrences are pull request merges; every other event's are tasks entering a lane.
MERGE_EVENT = "MERGED"

_PULL = re.compile(r"https://github\.com/[^/]+/([^/]+)/pull/(\d+)")
#: The shortest abbreviated commit a run parameter may name and still pair with a merge.
_MIN_ABBREV = 7


@dataclass(frozen=True)
class Occurrence:
    """One time a Board event happened: a merge when `sha` is set, else a task entering a lane."""

    key: str
    at: float
    """Epoch seconds."""
    tasks: tuple[str, ...]
    sha: str | None = None
    pr: Mapping[str, object] | None = None
    """For a merge, the pull request as `{repo, number, url}`."""


def _epoch(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def pull_occurrences(pulls: Mapping[str, Sequence[Mapping]]) -> list[Occurrence]:
    """One occurrence per merged pull request that carries its merge commit, with every task that cites it.

    `pulls` is the feed's pull request records by task.
    """
    merged: dict[str, Occurrence] = {}
    for task, records in pulls.items():
        for record in records:
            sha, at, found = record.get("merge_sha"), record.get("merged_at"), _PULL.fullmatch(record["url"])
            if not (record.get("merged") and sha and at and found):
                continue
            seen = merged.get(sha)
            tasks = (*seen.tasks, task) if seen and task not in seen.tasks else seen.tasks if seen else (task,)
            pr = {"repo": found[1], "number": int(found[2]), "url": record["url"]}
            merged[sha] = Occurrence(sha, _epoch(at), tasks, sha, pr)
    return list(merged.values())


def _names(value: str, sha: str) -> bool:
    """Whether the commit `value` is `sha`, either spelled out in full or abbreviated."""
    short, long = sorted((value.lower(), sha.lower()), key=len)
    return len(short) >= _MIN_ABBREV and long.startswith(short)


def _keyed(occurrences: Sequence[Occurrence], value: str, by_sha: bool) -> Occurrence | None:
    """The newest occurrence a run parameter's `value` names: a commit for merges, a task for the rest."""
    named = [o for o in occurrences if (o.sha is not None and _names(value, o.sha)) or (not by_sha and value in o.tasks)]
    return named[-1] if named else None


def _entry(run: Mapping, inferred: bool, ambiguous: int) -> dict:
    steps = dict(run.get("steps", {}))
    return {
        "runId": run["runId"],
        "status": run["status"],
        **({"raw": run["raw"]} if run.get("raw") else {}),
        "startedAt": run["startedAt"],
        "finishedAt": run.get("finishedAt", ""),
        "steps": steps,
        "step": next((name for name, status in steps.items() if status == "running"), ""),
        "inferred": inferred,
        "ambiguous": ambiguous,
    }


def pair(occurrences: Sequence[Occurrence], runs: Sequence[Mapping], keys: CommitKeys | None) -> dict[str, dict]:
    """Each occurrence's run of one workflow, by occurrence key.

    `runs` are the workflow's recent runs (`Dag.recent`), `keys` its instance's `[runs.commit]` (None: time only).
    An occurrence no run pairs with is left out.
    """
    ordered = sorted(occurrences, key=lambda o: o.at)
    by_sha = any(o.sha is not None for o in ordered)
    param = None if keys is None else keys.after if by_sha else keys.task
    paired: dict[str, tuple[tuple[int, float], dict]] = {}
    previous = float("-inf")
    for start, run in sorted(((_epoch(r["startedAt"]), r) for r in runs if r.get("startedAt")), key=lambda p: p[0]):
        value = run.get("params", {}).get(param) if param else None
        inferred, ambiguous = value is None, 0
        if value is None:
            earlier = [o for o in ordered if o.at <= start]
            match = earlier[-1] if earlier else None
            ambiguous = sum(o.at > previous for o in earlier[:-1])
        else:
            match = _keyed(ordered, value, by_sha)
        previous = start
        rank = (0, -start) if inferred else (1, start)
        if match is not None and (match.key not in paired or rank > paired[match.key][0]):
            paired[match.key] = (rank, _entry(run, inferred, ambiguous))
    return {key: entry for key, (_, entry) in paired.items()}


def build(
    events: Mapping[str, Sequence[Occurrence]],
    ties: Mapping[str, Sequence[str]],
    runs: Mapping[str, Sequence[Mapping]],
    keys: Callable[[str], CommitKeys | None],
) -> dict[str, list[dict]]:
    """Each tied event's rows, newest occurrence first: the occurrence and the run of every workflow tied to it.

    `ties` lists the workflows (`<instance>/<workflow>`) tied to each event, `runs` each workflow's recent runs and
    `keys` the `[runs.commit]` of a workflow's instance.
    """
    ledgers: dict[str, list[dict]] = {}
    for event, dags in ties.items():
        occurrences = events.get(event, ())
        paired = {dag: pair(occurrences, runs.get(dag, ()), keys(dag)) for dag in dags}
        ledgers[event] = [
            {
                "key": o.key,
                "at": o.at,
                "tasks": list(o.tasks),
                **({"sha": o.sha, "pr": dict(o.pr)} if o.sha is not None and o.pr is not None else {}),
                "runs": {dag: found[o.key] for dag, found in paired.items() if o.key in found},
            }
            for o in sorted(occurrences, key=lambda o: o.at, reverse=True)
        ]
    return ledgers
