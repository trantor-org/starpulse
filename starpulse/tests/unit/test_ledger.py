"""The Ledger pairs each Board transition's occurrence with the workflow runs it caused.

A merge is the occurrence of the Board's `MERGED` event; any other tied event's occurrences are a task entering the
lane the event reaches. A run carries its commit (or task) in a parameter `[runs.commit]` names, which pairs it
for certain; a run with no such parameter pairs with the newest occurrence before it started, marked inferred.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from starpulse.config import CommitKeys
from starpulse.ledger import Occurrence, build, pair, pull_occurrences

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
