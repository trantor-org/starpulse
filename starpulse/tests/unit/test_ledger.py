"""The Ledger pairs each Board transition's occurrence with the workflow runs it caused.

A merge is the occurrence of the Board's `MERGED` event; any other tied event's occurrences are a task entering the
lane the event reaches. A run carries its commit (or task) in a parameter `[runs.commit]` names, which pairs it
for certain; a run with no such parameter pairs with the newest occurrence before it started, marked inferred.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from starpulse._internal.projections import ledger
from starpulse._internal.projections.ledger import Occurrence, _matches, build, page, pair, pull_occurrences, reruns, strip
from starpulse._internal.settings.config import CommitKeys

KEYS = CommitKeys(after="AFTER", before="BEFORE", force="FORCE", task="TASK")
SHA_A, SHA_B, SHA_C = "a" * 40, "b" * 40, "c" * 40
BASE = datetime(2026, 10, 7, tzinfo=UTC)


def t(seconds: float) -> float:
    """Epoch seconds `seconds` after the test's base instant."""
    return (BASE + timedelta(seconds=seconds)).timestamp()


def merge(sha: str, at: float, *tasks: str) -> Occurrence:
    return Occurrence(key=sha, at=t(at), tasks=tasks, sha=sha, pr={"repo": "trantor", "number": 1, "url": "u"})


def run(run_id: str, start: float, params: Mapping[str, str] | None = None, **fields: object) -> dict:
    iso = lambda at: (BASE + timedelta(seconds=at)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    return {
        "runId": run_id,
        "status": "succeeded",
        "startedAt": iso(start),
        "finishedAt": iso(start + 30),
        "params": dict(params or {}),
        "steps": {"validate": "succeeded", "apply": "succeeded"},
        **fields,
    }


def test_a_run_whose_parameters_carry_the_commit_pairs_with_that_merge_and_is_not_inferred() -> None:
    merges = [merge(SHA_A, 10), merge(SHA_B, 20)]
    runs = [run("r1", 25, {"AFTER": SHA_A, "BEFORE": "0" * 40})]

    paired = pair(merges, runs, KEYS)

    assert paired[SHA_A]["runId"] == "r1"
    assert paired[SHA_A]["inferred"] is False
    assert paired[SHA_A]["ambiguous"] == 0
    assert SHA_B not in paired


def test_a_run_naming_a_commit_no_merge_has_pairs_with_nothing_instead_of_the_newest_merge() -> None:
    assert pair([merge(SHA_A, 10)], [run("r1", 25, {"AFTER": SHA_C})], KEYS) == {}


def test_an_abbreviated_commit_pairs_with_the_merge_whose_sha_it_begins() -> None:
    paired = pair([merge(SHA_A, 10)], [run("r1", 25, {"AFTER": SHA_A[:9]})], KEYS)

    assert paired[SHA_A]["inferred"] is False


def test_a_keyless_run_pairs_with_the_newest_earlier_merge_and_is_marked_inferred() -> None:
    merges = [merge(SHA_A, 10), merge(SHA_B, 20), merge(SHA_C, 300)]

    paired = pair(merges, [run("r1", 25)], None)

    assert paired[SHA_B]["runId"] == "r1"
    assert paired[SHA_B]["inferred"] is True
    assert set(paired) == {SHA_B}


def test_a_run_without_the_declared_parameter_is_paired_by_time_even_when_keys_are_declared() -> None:
    paired = pair([merge(SHA_A, 10)], [run("scheduled", 40, {"REPOSITORY": "x"})], KEYS)

    assert paired[SHA_A]["inferred"] is True


def test_a_run_that_started_before_every_merge_pairs_with_none() -> None:
    assert pair([merge(SHA_A, 100)], [run("r1", 25)], None) == {}


def test_a_run_window_spanning_two_merges_marks_the_pairing_ambiguous() -> None:
    # the DAG last ran at 5; merges at 10 and 20 both landed before it ran again at 25
    merges = [merge(SHA_A, 10), merge(SHA_B, 20)]
    runs = [run("before", 5), run("after", 25)]

    paired = pair(merges, runs, None)

    assert paired[SHA_B]["runId"] == "after"
    assert paired[SHA_B]["ambiguous"] == 1
    assert SHA_A not in paired


def test_a_merge_alone_in_a_run_window_is_not_ambiguous() -> None:
    merges = [merge(SHA_A, 10), merge(SHA_B, 20)]
    runs = [run("first", 12), run("second", 25)]

    paired = pair(merges, runs, None)

    assert (paired[SHA_A]["runId"], paired[SHA_A]["ambiguous"]) == ("first", 0)
    assert (paired[SHA_B]["runId"], paired[SHA_B]["ambiguous"]) == ("second", 0)


def test_a_keyed_run_outranks_an_inferred_one_for_the_same_merge() -> None:
    runs = [run("by-time", 40), run("by-key", 30, {"AFTER": SHA_A})]

    paired = pair([merge(SHA_A, 10)], runs, KEYS)

    assert paired[SHA_A]["runId"] == "by-key"


def test_a_rerun_replaces_the_earlier_run_of_the_same_merge() -> None:
    runs = [run("first", 30, {"AFTER": SHA_A}, status="failed"), run("rerun", 90, {"AFTER": SHA_A})]

    assert pair([merge(SHA_A, 10)], runs, KEYS)[SHA_A]["runId"] == "rerun"


def test_the_pairing_carries_the_runs_status_times_and_per_step_status() -> None:
    steps = {"validate": "succeeded", "apply": "running", "verify": "not_started"}

    entry = pair([merge(SHA_A, 10)], [run("r1", 25, {"AFTER": SHA_A}, status="running", steps=steps)], KEYS)[SHA_A]

    assert entry["status"] == "running"
    assert entry["startedAt"] == "2026-10-07T00:00:25Z"
    assert entry["steps"] == steps
    assert entry["step"] == "apply"


def test_a_run_between_steps_has_no_current_step() -> None:
    entry = pair([merge(SHA_A, 10)], [run("r1", 25, {"AFTER": SHA_A})], KEYS)[SHA_A]

    assert entry["step"] == ""


def test_a_task_transition_pairs_by_the_task_parameter_when_the_instance_declares_one() -> None:
    occurrences = [
        Occurrence(key="TASK-1@10", at=t(10), tasks=("TASK-1",)),
        Occurrence(key="TASK-2@20", at=t(20), tasks=("TASK-2",)),
    ]

    paired = pair(occurrences, [run("r1", 30, {"TASK": "TASK-1"})], KEYS)

    assert paired["TASK-1@10"]["runId"] == "r1"
    assert paired["TASK-1@10"]["inferred"] is False
    assert "TASK-2@20" not in paired


def test_a_task_transition_with_no_task_parameter_pairs_by_time_marked_inferred() -> None:
    occurrences = [Occurrence(key="TASK-1@10", at=t(10), tasks=("TASK-1",))]

    paired = pair(occurrences, [run("r1", 30)], CommitKeys(after="AFTER"))

    assert paired["TASK-1@10"]["inferred"] is True


def test_a_pull_request_merged_in_the_window_is_a_merge_occurrence_carrying_its_tasks_and_pr() -> None:
    pulls = {
        "TASK-1": [{"url": "https://github.com/o/trantor/pull/7", "merged": True, "merge_sha": SHA_A,
                    "merged_at": "2026-10-07T00:01:00Z"}],
        "TASK-2": [{"url": "https://github.com/o/trantor/pull/7", "merged": True, "merge_sha": SHA_A,
                    "merged_at": "2026-10-07T00:01:00Z"},
                   {"url": "https://github.com/o/trantor/pull/8", "merged": False, "merge_sha": None,
                    "merged_at": None}],
    }

    (occurrence,) = pull_occurrences(pulls)

    assert occurrence.sha == SHA_A
    assert occurrence.tasks == ("TASK-1", "TASK-2")
    assert occurrence.pr == {"repo": "trantor", "number": 7, "url": "https://github.com/o/trantor/pull/7"}
    assert occurrence.at == t(60)


def test_a_merged_record_with_no_merge_commit_is_not_an_occurrence() -> None:
    pulls = {"TASK-1": [{"url": "https://github.com/o/r/pull/7", "merged": True, "merge_sha": None,
                         "merged_at": None}]}

    assert pull_occurrences(pulls) == []


def test_the_ledger_pairs_each_tied_workflow_of_each_event_newest_occurrence_first() -> None:
    events = {"MERGED": [merge(SHA_A, 10), merge(SHA_B, 20)], "TESTED": [Occurrence("T@5", t(5), ("T",))]}
    ties = {"MERGED": ["dagu/apply", "dagu/refresh"], "TESTED": ["dagu/apply"]}
    runs = {
        "dagu/apply": [run("a", 12, {"AFTER": SHA_A}), run("t", 9)],
        "dagu/refresh": [run("g", 22)],
    }

    ledgers = build(events, ties, runs, lambda dag: KEYS)

    merged = ledgers["MERGED"]
    assert [row["key"] for row in merged] == [SHA_B, SHA_A]
    assert merged[1]["sha"] == SHA_A
    assert merged[1]["tasks"] == []
    assert merged[1]["pr"]["number"] == 1
    assert merged[1]["runs"]["dagu/apply"]["runId"] == "a"
    assert merged[0]["runs"]["dagu/refresh"]["runId"] == "g"
    assert merged[0]["runs"]["dagu/refresh"]["inferred"] is True
    assert ledgers["TESTED"][0]["runs"]["dagu/apply"]["runId"] == "t"
    assert "sha" not in ledgers["TESTED"][0]


def failed(run_id: str, start: float, params: Mapping[str, str] | None = None) -> dict:
    return run(run_id, start, params, status="failed", steps={"validate": "succeeded", "apply": "failed"})


def ledger_of(runs: list[dict], rule: str, *merges: Occurrence) -> dict[str, dict]:
    """The MERGED ledger of one cued workflow, `merges` newest first, by merge key."""
    rows = build({"MERGED": list(merges)}, {"MERGED": ["dagu/apply"]}, {"dagu/apply": runs}, lambda dag: KEYS, lambda e, d: rule)
    return {row["key"]: row for row in rows["MERGED"]}


def test_a_failed_run_is_an_open_failure_that_pins_its_merge_until_its_cue_resolves() -> None:
    rows = ledger_of([failed("f", 15, {"AFTER": SHA_A})], "next", merge(SHA_A, 10), merge(SHA_B, 100))

    fail = rows[SHA_A]["fails"]["dagu/apply"]
    assert (fail["runId"], fail["step"], fail["resolves"], fail["resolved"]) == ("f", "apply", "next", None)
    assert (rows[SHA_A]["pinned"], rows[SHA_B]["pinned"]) == (True, False)


def test_a_run_that_did_not_fail_carries_no_resolution() -> None:
    rows = ledger_of([run("g", 15, {"AFTER": SHA_A})], "next", merge(SHA_A, 10))

    assert rows[SHA_A]["fails"] == {}
    assert rows[SHA_A]["pinned"] is False


def test_a_resolves_next_failure_clears_on_the_next_successful_run_of_that_workflow() -> None:
    runs = [failed("f", 15, {"AFTER": SHA_A}), run("g", 105, {"AFTER": SHA_B})]

    rows = ledger_of(runs, "next", merge(SHA_A, 10), merge(SHA_B, 100))

    assert rows[SHA_A]["fails"]["dagu/apply"]["resolved"] == {"runId": "g", "at": runs[1]["finishedAt"]}
    assert rows[SHA_A]["pinned"] is False


def test_a_resolves_next_failure_is_not_cleared_by_a_run_that_is_not_green_or_that_started_before_it() -> None:
    runs = [
        run("earlier", 5, {"AFTER": SHA_A}),
        failed("f", 15, {"AFTER": SHA_A}),
        run("busy", 105, {"AFTER": SHA_B}, status="running"),
        failed("again", 205, {"AFTER": SHA_B}),
    ]

    rows = ledger_of(runs, "next", merge(SHA_A, 10), merge(SHA_B, 100))

    assert rows[SHA_A]["fails"]["dagu/apply"]["resolved"] is None
    assert rows[SHA_A]["pinned"] is True


def test_a_resolves_forced_failure_is_not_cleared_by_a_successful_run_that_was_not_forced() -> None:
    runs = [failed("f", 15, {"AFTER": SHA_A}), run("g", 105, {"AFTER": SHA_B})]

    rows = ledger_of(runs, "forced", merge(SHA_A, 10), merge(SHA_B, 100))

    assert rows[SHA_A]["fails"]["dagu/apply"]["resolved"] is None
    assert rows[SHA_A]["pinned"] is True


def test_a_resolves_forced_failure_clears_on_a_successful_forced_run_that_covers_its_merge() -> None:
    forced = run("force", 105, {"AFTER": SHA_B, "FORCE": "1"})

    rows = ledger_of([failed("f", 15, {"AFTER": SHA_A}), forced], "forced", merge(SHA_A, 10), merge(SHA_B, 100))

    assert rows[SHA_A]["fails"]["dagu/apply"]["resolved"] == {"runId": "force", "at": forced["finishedAt"]}
    assert rows[SHA_A]["pinned"] is False


def test_a_forced_run_that_carries_no_commit_covers_every_failure_before_it() -> None:
    runs = [failed("f", 15, {"AFTER": SHA_A}), run("force", 105, {"FORCE": "1"})]

    assert ledger_of(runs, "forced", merge(SHA_A, 10))[SHA_A]["pinned"] is False


@pytest.mark.parametrize(
    "forced",
    [
        pytest.param({"status": "failed"}, id="failed"),
        pytest.param({"status": "running"}, id="still-running"),
        pytest.param({"params": {"AFTER": SHA_A, "FORCE": "0"}}, id="force-switched-off"),
        pytest.param({"params": {"AFTER": SHA_A, "FORCE": ""}}, id="force-empty"),
        pytest.param({"params": {"AFTER": SHA_A, "FORCE": "1"}, "startedAt": "2026-10-06T00:00:00Z"}, id="before-the-failure"),
    ],
)
def test_a_forced_run_that_did_not_succeed_or_was_not_forced_or_came_first_leaves_the_failure_open(forced: dict) -> None:
    attempt = {**run("force", 105, {"AFTER": SHA_A, "FORCE": "1"}), **forced}

    rows = ledger_of([failed("f", 15, {"AFTER": SHA_A}), attempt], "forced", merge(SHA_A, 10))

    assert rows[SHA_A]["pinned"] is True


def test_a_forced_run_of_an_older_commit_does_not_cover_a_newer_failure() -> None:
    runs = [failed("f", 105, {"AFTER": SHA_B}), run("force", 205, {"AFTER": SHA_A, "FORCE": "1"})]

    rows = ledger_of(runs, "forced", merge(SHA_A, 10), merge(SHA_B, 100))

    assert rows[SHA_B]["pinned"] is True


def test_a_forced_run_of_a_commit_the_ledger_does_not_hold_covers_nothing() -> None:
    runs = [failed("f", 15, {"AFTER": SHA_A}), run("force", 105, {"AFTER": SHA_C, "FORCE": "1"})]

    assert ledger_of(runs, "forced", merge(SHA_A, 10))[SHA_A]["pinned"] is True


def test_a_forced_failure_stays_open_when_the_instance_declares_no_force_parameter() -> None:
    runs = [failed("f", 15, {"AFTER": SHA_A}), run("force", 105, {"AFTER": SHA_A, "FORCE": "1"})]
    keys = CommitKeys(after="AFTER")

    rows = build({"MERGED": [merge(SHA_A, 10)]}, {"MERGED": ["dagu/apply"]}, {"dagu/apply": runs}, lambda dag: keys, lambda e, d: "forced")

    assert rows["MERGED"][0]["pinned"] is True


def test_each_workflow_resolves_by_its_own_cue_and_an_unrulled_workflow_resolves_on_its_next_success() -> None:
    runs = {
        "dagu/apply": [failed("f", 15, {"AFTER": SHA_A}), run("g", 105, {"AFTER": SHA_B})],
        "dagu/refresh": [failed("rf", 15, {"AFTER": SHA_A}), run("rg", 105, {"AFTER": SHA_B})],
    }
    rules = {("MERGED", "dagu/apply"): "forced"}

    (newer, older) = build(
        {"MERGED": [merge(SHA_A, 10), merge(SHA_B, 100)]},
        {"MERGED": ["dagu/apply", "dagu/refresh"]},
        runs,
        lambda dag: KEYS,
        lambda event, dag: rules.get((event, dag), "next"),
    )["MERGED"]

    assert older["fails"]["dagu/apply"]["resolved"] is None
    assert older["fails"]["dagu/refresh"]["resolved"]["runId"] == "rg"
    assert older["pinned"] is True
    assert newer["pinned"] is False


def test_a_green_retry_of_the_same_commit_shows_in_the_row_but_leaves_a_forced_failure_open() -> None:
    runs = [failed("f", 15, {"AFTER": SHA_A}), run("retry", 105, {"AFTER": SHA_A})]

    (row,) = ledger_of(runs, "forced", merge(SHA_A, 10)).values()

    assert row["runs"]["dagu/apply"]["runId"] == "retry"
    assert (row["fails"]["dagu/apply"]["runId"], row["pinned"]) == ("f", True)


def test_a_merge_that_failed_several_times_holds_its_latest_failure() -> None:
    runs = [failed("f1", 15, {"AFTER": SHA_A}), failed("f2", 105, {"AFTER": SHA_A}), run("g", 55, {"AFTER": SHA_B})]

    rows = ledger_of(runs, "next", merge(SHA_A, 10), merge(SHA_B, 50))

    assert rows[SHA_A]["fails"]["dagu/apply"]["runId"] == "f2"
    assert rows[SHA_A]["pinned"] is True


def child(sha: str, at: float, applied_by: str | None) -> Occurrence:
    merged = Occurrence(key=sha, at=t(at), tasks=(), sha=sha, pr={"repo": "skills", "number": 2, "url": "u"})
    return replace(merged, child=True, applied_by=applied_by)


def test_a_pinned_repositorys_merge_is_an_occurrence_that_names_the_merge_applying_it() -> None:
    url = "https://github.com/o/skills/pull/7"
    record = {"url": url, "merged": True, "merge_sha": SHA_A, "merged_at": BASE.isoformat(), "applied_by": SHA_B}
    pulls = {"TASK-1": [record]}

    (occurrence,) = pull_occurrences(pulls)

    assert (occurrence.child, occurrence.applied_by) == (True, SHA_B)


def test_a_merge_with_no_pin_bump_yet_is_a_child_and_unapplied() -> None:
    url = "https://github.com/o/skills/pull/7"
    record = {"url": url, "merged": True, "merge_sha": SHA_A, "merged_at": BASE.isoformat(), "applied_by": None}
    pulls = {"TASK-1": [record]}

    (occurrence,) = pull_occurrences(pulls)

    assert (occurrence.child, occurrence.applied_by) == (True, None)


def test_a_merge_the_parent_does_not_pin_is_not_a_child() -> None:
    url = "https://github.com/o/trantor/pull/7"
    pulls = {"TASK-1": [{"url": url, "merged": True, "merge_sha": SHA_A, "merged_at": BASE.isoformat()}]}

    (occurrence,) = pull_occurrences(pulls)

    assert occurrence.child is False


def test_a_child_merge_row_links_to_its_bump_and_the_bump_row_lists_what_it_applies() -> None:
    events = {"MERGED": [merge(SHA_A, 10), child(SHA_B, 20, SHA_A)]}

    rows = {row["key"]: row for row in build(events, {"MERGED": ["dagu/apply"]}, {}, lambda dag: None)["MERGED"]}

    assert rows[SHA_B]["appliedBy"] == SHA_A
    assert rows[SHA_A]["applies"] == [SHA_B]


def test_a_child_merge_before_any_bump_has_no_applier() -> None:
    events = {"MERGED": [child(SHA_B, 20, None)]}

    (row,) = build(events, {"MERGED": ["dagu/apply"]}, {}, lambda dag: None)["MERGED"]

    assert row["appliedBy"] is None


def test_a_child_merge_takes_no_run_and_does_not_make_the_parents_pairing_ambiguous() -> None:
    events = {"MERGED": [merge(SHA_A, 10), child(SHA_B, 20, None)]}
    runs = {"dagu/apply": [run("r1", 25)]}

    rows = {row["key"]: row for row in build(events, {"MERGED": ["dagu/apply"]}, runs, lambda dag: None)["MERGED"]}

    assert rows[SHA_B]["runs"] == {}
    assert rows[SHA_A]["runs"]["dagu/apply"]["runId"] == "r1"
    assert rows[SHA_A]["runs"]["dagu/apply"]["ambiguous"] == 0


def test_a_merge_the_parent_does_not_pin_has_neither_link_key() -> None:
    (row,) = build({"MERGED": [merge(SHA_A, 10)]}, {"MERGED": ["dagu/apply"]}, {}, lambda dag: None)["MERGED"]

    assert "appliedBy" not in row
    assert "applies" not in row


def rows(*times: float) -> list[dict]:
    """Ledger rows at `times`, newest first as `build` returns them."""
    return [{"key": f"m{at}", "at": at} for at in sorted(times, reverse=True)]


def keys_of(found: list[dict]) -> list[str]:
    return [row["key"] for row in found]


def test_pages_walk_the_ledger_with_no_overlap_or_gap_and_end_at_the_oldest_row() -> None:
    ledger = rows(*range(100, 107))
    seen: list[str] = []
    before: float | None = None
    for _ in range(10):
        found, more = page(ledger, before=before, limit=3, since=0)
        seen += keys_of(found)
        if not more:
            break
        before = found[-1]["at"]

    assert seen == keys_of(ledger)
    assert more is False


def test_rows_sharing_the_boundary_second_travel_together_so_no_page_boundary_drops_one() -> None:
    ledger = rows(105, 104, 104, 104, 103)

    first, more = page(ledger, before=None, limit=2, since=0)
    second, _ = page(ledger, before=first[-1]["at"], limit=2, since=0)

    assert (len(first), more) == (4, True)
    assert [row["at"] for row in second] == [103]


def test_a_page_stops_at_the_since_edge_and_reports_nothing_older() -> None:
    ledger = rows(10, 20, 30, 40)

    found, more = page(ledger, before=None, limit=10, since=25)

    assert ([row["at"] for row in found], more) == ([40, 30], False)


def test_the_strip_counts_merges_failures_and_reruns_per_bucket_over_the_span() -> None:
    now = t(0)
    bad = {"dagu/apply": {"status": "failed"}}
    ledger = [
        {"key": "a", "at": now - 10, "fails": {}},
        {"key": "b", "at": now - 20, "fails": bad},
        {"key": "c", "at": now - 130, "fails": {}},
        {"key": "old", "at": now - 1000, "fails": bad},
    ]

    found = strip(ledger, [now - 5, now - 135], now=now, span=300, bucket=100)

    assert found["since"] == now - 300
    assert found["bucket"] == 100
    assert found["buckets"] == [
        {"merges": 0, "failed": 0, "reruns": 0},
        {"merges": 1, "failed": 0, "reruns": 1},
        {"merges": 2, "failed": 1, "reruns": 1},
    ]


def test_a_run_whose_force_parameter_is_set_is_a_rerun_and_one_with_no_force_key_is_not() -> None:
    forced, plain, off = run("f", 10, {"FORCE": "true"}), run("p", 20), run("o", 30, {"FORCE": "false"})

    assert reruns([forced, plain, off], KEYS) == [t(10)]
    assert reruns([forced], None) == []
    assert reruns([forced], CommitKeys(after="AFTER")) == []


def _reference_matches(occurrences: list[Occurrence], runs: list[dict], keys: object) -> list[tuple]:
    """The pairing as first written: a scan of every occurrence for each run, the oracle the fast one must equal."""

    def names(value: str, sha: str) -> bool:
        short, long = sorted((value.lower(), sha.lower()), key=len)
        return len(short) >= 7 and long.startswith(short)

    def keyed(ordered: list[Occurrence], value: str, by_sha: bool) -> Occurrence | None:
        named = [o for o in ordered if (o.sha is not None and names(value, o.sha)) or (not by_sha and value in o.tasks)]
        return named[-1] if named else None

    epoch = lambda iso: datetime.fromisoformat(iso).timestamp()  # noqa: E731
    ordered = sorted(occurrences, key=lambda o: o.at)
    by_sha = any(o.sha is not None for o in ordered)
    param = None if keys is None else keys.after if by_sha else keys.task  # type: ignore[attr-defined]
    out, previous = [], float("-inf")
    for start, run in sorted(((epoch(r["startedAt"]), r) for r in runs if r.get("startedAt")), key=lambda p: p[0]):
        value = run.get("params", {}).get(param) if param else None
        inferred, ambiguous = value is None, 0
        if value is None:
            earlier = [o for o in ordered if o.at <= start]
            match = earlier[-1] if earlier else None
            ambiguous = sum(o.at > previous for o in earlier[:-1])
        else:
            match = keyed(ordered, value, by_sha)
        previous = start
        if match is not None:
            out.append((match, start, run, inferred, ambiguous))
    return out


@pytest.mark.parametrize("seed", range(40))
@pytest.mark.parametrize("merges", [True, False])
def test_the_pairing_equals_the_scan_of_every_occurrence_for_each_run(seed: int, merges: bool) -> None:
    rng = random.Random(seed)
    shas = ["".join(rng.choice("0123456789abcdef") for _ in range(40)) for _ in range(12)]
    # moments repeat, so equal times and runs starting on an occurrence are exercised
    moments = [rng.choice(range(0, 400, 10)) for _ in range(30)]
    occurrences = [
        Occurrence(f"k{i}", t(at), (f"TASK-{rng.randrange(8)}", f"TASK-{rng.randrange(8)}"), shas[i % 12] if merges else None)
        for i, at in enumerate(moments)
    ]
    values = [None, "", "TASK-3", "TASK-99", "zzzzzzzz"] + [s[: rng.choice([3, 7, 12, 40])] for s in shas] + [s.upper() for s in shas[:3]]
    runs = []
    for i in range(40):
        value = rng.choice(values)
        params = {} if value is None else {"AFTER": value} if merges else {"TASK": value}
        runs.append(run(f"r{i}", rng.choice(range(-20, 450, 5)), params, status=rng.choice(["succeeded", "failed"])))
    runs.append({**run("nostart", 0), "startedAt": ""})

    assert _matches(occurrences, runs, KEYS) == _reference_matches(occurrences, runs, KEYS)
    assert _matches(occurrences, runs, None) == _reference_matches(occurrences, runs, None)


def test_build_pairs_the_runs_of_a_workflow_once_for_its_runs_and_its_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    paired: list[int] = []
    pair_runs = ledger._matches
    monkeypatch.setattr(ledger, "_matches", lambda *args: paired.append(1) or pair_runs(*args))

    rows = build({"E": [merge(SHA_A, 10)]}, {"E": ["ci/a", "ci/b"]}, {"ci/a": [run("r1", 20, {"AFTER": SHA_A}, status="failed")]}, lambda dag: KEYS)

    assert len(paired) == 2
    assert rows["E"][0]["fails"]["ci/a"]["runId"] == "r1"
    assert rows["E"][0]["pinned"] is True
