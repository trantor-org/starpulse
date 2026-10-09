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

A workflow's latest failed run of an occurrence is an *open failure*, and pins the occurrence, until its cue's `resolves` rule clears it: `next`
on the next successful run of that workflow, `forced` only on a successful forced run (the instance's `force`
parameter set) that covers the occurrence, that is one that names a commit (or task) no older than it, or none.

A merge in a repository the parent pins (`[[repos]]`, see `starpulse._internal.config.pins`) is a *child* merge: it takes no run of its
own and does not count toward a parent merge's ambiguity. Its row names `appliedBy`, the parent merge whose pin bump
includes it (None until one does), and that merge's row lists it in `applies`.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from starpulse._internal.config.config import CommitKeys

__all__ = ["MERGE_EVENT", "NEXT", "PAGE", "STRIP_BUCKET", "Occurrence", "build", "page", "pair", "pull_occurrences", "reruns", "strip"]

#: The Board event whose occurrences are pull request merges; every other event's are tasks entering a lane.
MERGE_EVENT = "MERGED"

#: How a cue's failure resolves when its machine declares no `resolves`: on the workflow's next success.
NEXT = "next"
#: A `force` parameter set to one of these is a plain run.
_UNFORCED = frozenset({"", "0", "false"})

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
    child: bool = False
    """The merge is in a repository the parent pins (`[[repos]]`): a pin bump applies it, not a run of its own."""
    applied_by: str | None = None
    """For a child merge, the key of the parent merge whose pin bump includes it; none while no bump has."""


@lru_cache(maxsize=65536)  # every rebuild reads the same run and pull timestamps again
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
            merged[sha] = Occurrence(sha, _epoch(at), tasks, sha, pr, "applied_by" in record, record.get("applied_by"))
    return list(merged.values())


def _names(value: str, sha: str) -> bool:
    """Whether the commit `value` is `sha`, either spelled out in full or abbreviated."""
    value, sha = value.lower(), sha.lower()
    short, long = (value, sha) if len(value) <= len(sha) else (sha, value)
    return len(short) >= _MIN_ABBREV and long.startswith(short)


def _keyed(occurrences: Sequence[Occurrence], value: str, by_sha: bool) -> Occurrence | None:
    """The newest occurrence a run parameter's `value` names: a commit for merges, a task for the rest."""
    return next(
        (o for o in reversed(occurrences) if (o.sha is not None and _names(value, o.sha)) or (not by_sha and value in o.tasks)),
        None,
    )


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


def _matches(occurrences: Sequence[Occurrence], runs: Sequence[Mapping], keys: CommitKeys | None) -> list[tuple]:
    """Every run of one workflow with the occurrence it pairs with, oldest run first: `(occurrence, start, run, inferred, ambiguous)`.

    A run that pairs with no occurrence is left out.
    """
    ordered = sorted(occurrences, key=lambda o: o.at)
    ats = [o.at for o in ordered]
    by_sha = any(o.sha is not None for o in ordered)
    param = None if keys is None else keys.after if by_sha else keys.task
    out = []
    previous = float("-inf")
    for start, run in sorted(((_epoch(r["startedAt"]), r) for r in runs if r.get("startedAt")), key=lambda p: p[0]):
        value = run.get("params", {}).get(param) if param else None
        inferred, ambiguous = value is None, 0
        if value is None:
            reached = bisect_right(ats, start)  # the occurrences at or before the run's start
            match = ordered[reached - 1] if reached else None
            ambiguous = max(0, reached - 1 - bisect_right(ats, previous))  # those before the match, after the previous run
        else:
            match = _keyed(ordered, value, by_sha)
        previous = start
        if match is not None:
            out.append((match, start, run, inferred, ambiguous))
    return out


def pair(
    occurrences: Sequence[Occurrence], runs: Sequence[Mapping], keys: CommitKeys | None, matches: list[tuple] | None = None
) -> dict[str, dict]:
    """Each occurrence's run of one workflow, by occurrence key.

    `runs` are the workflow's recent runs (`Dag.recent`), `keys` its instance's `[runs.commit]` (None: time only).
    An occurrence no run pairs with is left out. `matches` is `_matches` of the same three, when the caller has it.
    """
    paired: dict[str, tuple[tuple[int, float], dict]] = {}
    for match, start, run, inferred, ambiguous in _matches(occurrences, runs, keys) if matches is None else matches:
        rank = (0, -start) if inferred else (1, start)
        if match.key not in paired or rank > paired[match.key][0]:
            paired[match.key] = (rank, _entry(run, inferred, ambiguous))
    return {key: entry for key, (_, entry) in paired.items()}


def _forced(run: Mapping, keys: CommitKeys | None) -> bool:
    """Whether `run` was started with the instance's `force` parameter set."""
    flag = run.get("params", {}).get(keys.force) if keys is not None and keys.force else None
    return flag is not None and flag.lower() not in _UNFORCED


def _covers(failed: Occurrence, forced: Mapping, ordered: Sequence[Occurrence], keys: CommitKeys | None) -> bool:
    """Whether the forced run `forced` reapplies `failed`: it names no commit (or task), or one at least as new.

    A commit the ledger does not hold covers nothing, as it is more likely older than the failure than newer.
    """
    by_sha = failed.sha is not None
    param = None if keys is None else keys.after if by_sha else keys.task
    value = forced.get("params", {}).get(param) if param else None
    if value is None:
        return True
    named = _keyed(ordered, value, by_sha)
    return named is not None and named.at >= failed.at


def _resolution(
    failed: Occurrence, began: float, timed: Sequence[tuple[float, Mapping]], rule: str, keys: CommitKeys | None, ordered: Sequence[Occurrence]
) -> dict | None:
    """The first successful run after the one that failed at `began` that the cue's `rule` accepts, as `{runId, at}`, else None.

    `timed` is the workflow's started runs as `(start, run)`, oldest first.
    """
    for start, run in timed:
        if run["status"] != "succeeded" or start <= began:
            continue
        if rule == NEXT or (_forced(run, keys) and _covers(failed, run, ordered, keys)):
            return {"runId": run["runId"], "at": run.get("finishedAt", "")}
    return None


def failures(
    occurrences: Sequence[Occurrence],
    runs: Sequence[Mapping],
    keys: CommitKeys | None,
    rule: str,
    matches: list[tuple] | None = None,
) -> dict[str, dict]:
    """Each occurrence's failure of one workflow, by occurrence key: its latest run that failed, whichever run the row shows.

    A failure is `{runId, step, startedAt, finishedAt, resolves, resolved}`: the step that failed, the `rule` its cue
    resolves by and the run that cleared it (None while it is open). A later run of the occurrence that succeeds does
    not clear a `forced` failure, so the failure is judged apart from the run `pair` shows. `matches` is `_matches` of
    `occurrences`, `runs` and `keys`, when the caller has it.
    """
    ordered = sorted(occurrences, key=lambda o: o.at)
    timed = sorted(((_epoch(r["startedAt"]), r) for r in runs if r.get("startedAt")), key=lambda p: p[0])
    latest: dict[str, tuple[float, Mapping, Occurrence]] = {}
    for match, start, run, _inferred, _ambiguous in _matches(occurrences, runs, keys) if matches is None else matches:
        if run["status"] == "failed":
            latest[match.key] = (start, run, match)
    return {
        key: {
            "runId": run["runId"],
            "step": next((name for name, status in run.get("steps", {}).items() if status == "failed"), ""),
            "startedAt": run["startedAt"],
            "finishedAt": run.get("finishedAt", ""),
            "resolves": rule,
            "resolved": _resolution(match, start, timed, rule, keys, ordered),
        }
        for key, (start, run, match) in latest.items()
    }


def build(
    events: Mapping[str, Sequence[Occurrence]],
    ties: Mapping[str, Sequence[str]],
    runs: Mapping[str, Sequence[Mapping]],
    keys: Callable[[str], CommitKeys | None],
    resolves: Callable[[str, str], str] = lambda event, dag: NEXT,
) -> dict[str, list[dict]]:
    """Each tied event's rows, newest occurrence first: the occurrence and the run of every workflow tied to it.

    `ties` lists the workflows (`<instance>/<workflow>`) tied to each event, `runs` each workflow's recent runs,
    `keys` the `[runs.commit]` of a workflow's instance and `resolves` how a failure of a workflow cued by an event
    resolves (`next` or `forced`). A row's `fails` holds each workflow's failure of it (`failures`), and the row is
    `pinned` while any is open.
    """
    ledgers: dict[str, list[dict]] = {}
    for event, dags in ties.items():
        occurrences = events.get(event, ())
        own = [o for o in occurrences if not o.child]
        matched = {dag: _matches(own, runs.get(dag, ()), keys(dag)) for dag in dags}
        paired = {dag: pair(own, runs.get(dag, ()), keys(dag), matched[dag]) for dag in dags}
        failed = {dag: failures(own, runs.get(dag, ()), keys(dag), resolves(event, dag), matched[dag]) for dag in dags}
        applies: dict[str, list[str]] = {}
        for c in occurrences:
            if c.applied_by is not None:
                applies.setdefault(c.applied_by, []).append(c.key)
        ledgers[event] = [
            {
                "key": o.key,
                "at": o.at,
                "tasks": list(o.tasks),
                **({"sha": o.sha, "pr": dict(o.pr)} if o.sha is not None and o.pr is not None else {}),
                **({"appliedBy": o.applied_by} if o.child else {}),
                **({"applies": applies[o.key]} if applies.get(o.key) else {}),
                "runs": {dag: found[o.key] for dag, found in paired.items() if o.key in found},
                "fails": (fails := {dag: found[o.key] for dag, found in failed.items() if o.key in found}),
                "pinned": any(fail["resolved"] is None for fail in fails.values()),
            }
            for o in sorted(occurrences, key=lambda o: o.at, reverse=True)
        ]
    return ledgers


#: Rows a page of the merge ledger holds.
PAGE = 20


def page(rows: Sequence[Mapping], *, before: float | None, limit: int, since: float) -> tuple[list[Mapping], bool]:
    """The next `limit` rows of `rows` (newest first) older than `before`, none from before `since`, and whether older remain.

    `before` is the `at` of the last row the reader holds (None: start at the newest). A page ends only between two
    different `at`s, so rows sharing the boundary second travel together and the next page, which starts strictly
    older, neither repeats nor skips one; such a page may hold more than `limit`.
    """
    live = [row for row in rows if row["at"] >= since and (before is None or row["at"] < before)]
    end = limit
    while 0 < end < len(live) and live[end]["at"] == live[end - 1]["at"]:
        end += 1
    return live[:end], end < len(live)


#: The width of one strip bucket: a quarter-hour, so a day is 96.
STRIP_BUCKET = 900.0


def strip(rows: Sequence[Mapping], reruns: Sequence[float], *, now: float, span: float, bucket: float) -> dict:
    """What the 24-hour strip draws without the rows: per `bucket` of the `span` ending `now`, how many merges landed,
    how many of those had a workflow fail on them (`fails`), and how many forced reruns started.

    `rows` are the merge ledger's and `reruns` the epoch starts of the forced runs (`reruns`). Anything outside the
    span is left out.
    """
    since = now - span
    buckets = [{"merges": 0, "failed": 0, "reruns": 0} for _ in range(math.ceil(span / bucket))]

    def count(at: float, field: str) -> None:
        if since <= at <= now:
            buckets[min(int((at - since) // bucket), len(buckets) - 1)][field] += 1

    for row in rows:
        count(row["at"], "merges")
        if row["fails"]:
            count(row["at"], "failed")
    for at in reruns:
        count(at, "reruns")
    return {"since": since, "bucket": bucket, "buckets": buckets}


def reruns(runs: Sequence[Mapping], keys: CommitKeys | None) -> list[float]:
    """The epoch starts of the runs started with the instance's `force` parameter set (`_forced`)."""
    return [_epoch(r["startedAt"]) for r in runs if r.get("startedAt") and _forced(r, keys)]
