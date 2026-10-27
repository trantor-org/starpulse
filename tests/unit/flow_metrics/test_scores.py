"""The cell score: ADR weights with missing parts renormalized, per kind x size cell and profile."""

import pytest
from starpulse.flow_metrics.scores import PullFacts, merged_pulls, pull_facts, score_cells, task_score

LABELS = {"labels": ["kind-execute", "size-5"]}


def slice_(
    task: str,
    *,
    clean: bool = True,
    prompts: int = 0,
    model: str = "sonnet",
    effort: str = "medium",
    raises: int = 0,
    lowers: int = 0,
) -> dict:
    return {
        "task": task,
        "complete": True,
        "clean": clean,
        "operator_prompts": prompts,
        "raises": raises,
        "lowers": lowers,
        "harnesses": ["claude-code"],
        "models": [model],
        "efforts": [effort],
    }


def test_all_parts_present_use_adr_weights() -> None:
    parts = {"clean": 100, "prompts": 100, "commits_after_ready": 0, "rating": 100, "time_to_merge": 0}
    assert task_score(parts) == pytest.approx(40 + 20 + 0 + 15 + 0)


def test_missing_parts_drop_out_and_the_rest_renormalize() -> None:
    parts = {"clean": 100, "prompts": 0, "commits_after_ready": None, "rating": None, "time_to_merge": None}
    assert task_score(parts) == pytest.approx(100 * 40 / 60)


def test_no_parts_is_no_score() -> None:
    assert task_score({"clean": None}) is None


def test_a_configured_weight_replaces_the_built_in_one() -> None:
    parts = {"clean": 100.0, "prompts": 0.0}

    assert task_score(parts, {"clean": 1, "prompts": 3}) == pytest.approx(25)


def test_cell_row_averages_task_scores_per_profile_with_github_parts() -> None:
    slices = [slice_("TASK-1"), slice_("TASK-2", clean=False, prompts=1), slice_("TASK-3", model="opus", effort="low")]
    tasks = dict.fromkeys(("TASK-1", "TASK-2", "TASK-3"), LABELS)
    facts = {"TASK-1": PullFacts(commits_after_ready=0, hours_to_merge=0.0)}
    rows = score_cells(slices, tasks, facts)
    by_profile = {r["profile"]: r for r in rows}
    # The first task: clean 100, prompts 100, commits 100, ttm 100, no rating -> 100.
    # The second task: clean 0, prompts 50, no PR facts -> (0*40 + 50*20) / 60.
    assert by_profile["sonnet-medium"]["score"] == pytest.approx((100 + 1000 / 60) / 2)
    assert by_profile["sonnet-medium"]["n"] == 2
    assert by_profile["opus-low"]["n"] == 1
    assert {(r["kind"], r["size"]) for r in rows} == {("execute", 5)}


def test_task_without_cell_labels_is_in_no_row() -> None:
    assert score_cells([slice_("TASK-9")], {"TASK-9": {"labels": []}}, {}) == []


def test_commits_after_ready_and_slow_merge_lower_the_score() -> None:
    fast = PullFacts(commits_after_ready=0, hours_to_merge=0.0)
    slow = PullFacts(commits_after_ready=3, hours_to_merge=48.0)
    rows = score_cells(
        [slice_("TASK-1"), slice_("TASK-2", model="opus")],
        {"TASK-1": LABELS, "TASK-2": LABELS},
        {"TASK-1": fast, "TASK-2": slow},
    )
    scores = {r["profile"]: r["score"] for r in rows}
    assert scores["sonnet-medium"] > scores["opus-medium"]


def test_a_raised_session_scores_its_rating_as_a_fail() -> None:
    plain = score_cells([slice_("TASK-1", clean=False)], {"TASK-1": LABELS}, {})
    raised = score_cells([slice_("TASK-1", clean=False, raises=1)], {"TASK-1": LABELS}, {})
    # Clean 0 and prompts 100 are present either way. A raise adds rating 0 at weight 15: 2000 / 75, not 2000 / 60.
    assert plain[0]["score"] == pytest.approx(2000 / 60)
    assert raised[0]["score"] == pytest.approx(2000 / 75)


def test_a_lowered_session_scores_its_rating_as_half() -> None:
    lowered = score_cells([slice_("TASK-1", clean=False, lowers=1)], {"TASK-1": LABELS}, {})
    assert lowered[0]["score"] == pytest.approx((2000 + 50 * 15) / 75)


def test_an_explicit_rating_overrides_the_implicit_one() -> None:
    rows = score_cells([slice_("TASK-1", clean=False, raises=1)], {"TASK-1": LABELS}, {}, ratings={"TASK-1": 100.0})
    assert rows[0]["score"] == pytest.approx((2000 + 100 * 15) / 75)


def test_a_cell_row_counts_the_tasks_whose_session_left_its_arm() -> None:
    slices = [slice_("TASK-1"), slice_("TASK-2", raises=1), slice_("TASK-3", lowers=1)]
    tasks = dict.fromkeys(("TASK-1", "TASK-2", "TASK-3"), LABELS)

    assert [(r["profile"], r["n"], r["off_arm"]) for r in score_cells(slices, tasks, {})] == [("sonnet-medium", 3, 2)]


def _transport(merged: str | None) -> object:
    answers = {
        "/repos/o/r/pulls/7": {"merged_at": merged, "created_at": "2026-01-01T00:00:00Z"},
        "/repos/o/r/issues/7/events?per_page=100": {
            "items": [{"event": "ready_for_review", "created_at": "2026-01-01T10:00:00Z"}]
        },
        "/repos/o/r/pulls/7/commits?per_page=100": {
            "items": [
                {"commit": {"committer": {"date": "2026-01-01T09:00:00Z"}}},
                {"commit": {"committer": {"date": "2026-01-01T11:00:00Z"}}},
            ]
        },
    }
    return lambda method, path, body: (200, answers[path])


def test_pull_facts_count_commits_after_the_last_ready_event_and_hours_to_merge() -> None:
    assert pull_facts(_transport("2026-01-01T22:00:00Z"), "o/r", 7) == PullFacts(1, 12.0)


def test_unmerged_pull_has_no_facts() -> None:
    assert pull_facts(_transport(None), "o/r", 7) is None


def test_merged_pulls_map_tasks_named_in_titles_to_merged_pull_numbers() -> None:
    listed = [
        {"number": 9, "title": "feat(TASK-5): add", "merged_at": "2026-01-02T00:00:00Z"},
        {"number": 8, "title": "fix(TASK-6): closed unmerged", "merged_at": None},
        {"number": 7, "title": "chore: no task", "merged_at": "2026-01-01T00:00:00Z"},
        {"number": 4, "title": "feat(TASK-5): older", "merged_at": "2026-01-01T00:00:00Z"},
    ]
    transport = lambda method, path, body: (200, {"items": listed})
    assert merged_pulls(transport, "o/r") == {"TASK-5": 9}
