"""A Task's History folds into one row: each Event type's effect, and the refusal of a type the fold does not know."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from starpulse.event_log.readmodel.fold import UnknownEvent, fold, replay
from starpulse.event_log.store import StoredEvent


def _events(*steps: tuple[str, dict[str, Any]]) -> list[StoredEvent]:
    return [
        StoredEvent(
            event_id=f"e-{version}",
            subject_kind="task",
            subject_id="TASK-1",
            version=version,
            type=type,
            schema_version=1,
            at=100.0 + version,
            actor="adin",
            writer="operator",
            definition_hash=None,
            causation_id=None,
            correlation_id=None,
            payload=payload,
        )
        for version, (type, payload) in enumerate(steps, start=1)
    ]


CREATED = ("TaskCreated", {"title": "Index it", "state": "Ready", "labels": ["a"], "fields": {"size": 3}})


def test_a_created_task_is_a_row_with_the_defaults_of_every_column():
    row = replay(_events(CREATED))

    assert row["id"] == "TASK-1"
    assert (row["title"], row["state"], row["labels"], row["fields"]) == ("Index it", "Ready", ["a"], {"size": 3})
    assert (row["version"], row["created_at"], row["updated_at"]) == (1, 101.0, 101.0)
    assert (row["archived"], row["assignee"], row["meta"], row["criteria"]) == (False, "", {}, [])


def test_an_edit_changes_own_fields_declared_fields_and_meta_and_a_null_removes_a_key():
    row = replay(
        _events(
            CREATED,
            ("FieldsEdited", {"changes": {"title": "Index more"}, "fields": {"size": None, "kind": "x"}, "meta": {"k": "v"}}),
        )
    )

    assert row["title"] == "Index more"
    assert row["fields"] == {"kind": "x"}
    assert row["meta"] == {"k": "v"}
    assert (row["version"], row["updated_at"]) == (2, 102.0)


def test_criteria_are_numbered_per_kind_and_checked_by_number():
    row = replay(
        _events(
            CREATED,
            ("CriterionAdded", {"kind": "acceptance", "text": "one"}),
            ("CriterionAdded", {"kind": "acceptance", "text": "two"}),
            ("CriterionAdded", {"kind": "done", "text": "d"}),
            ("CriterionChecked", {"kind": "acceptance", "n": 2, "checked": True, "evidence": "ok"}),
        )
    )

    assert row["criteria"] == [
        {"kind": "acceptance", "n": 1, "text": "one", "checked": False, "evidence": ""},
        {"kind": "acceptance", "n": 2, "text": "two", "checked": True, "evidence": "ok"},
        {"kind": "done", "n": 1, "text": "d", "checked": False, "evidence": ""},
    ]


def test_a_check_of_a_criterion_the_history_never_added_is_skipped_with_a_warning(caplog):
    row = replay(
        _events(
            CREATED,
            ("CriterionAdded", {"kind": "ac", "text": "one"}),
            ("CriterionChecked", {"kind": "ac", "n": 2, "checked": True, "evidence": "ok"}),
            ("Transitioned", {"to": "Review"}),
        )
    )

    assert row["criteria"] == [{"kind": "ac", "n": 1, "text": "one", "checked": False, "evidence": ""}]
    assert (row["state"], row["version"]) == ("Review", 4)
    assert "TASK-1: no ac criterion 2" in caplog.text


def test_a_claim_a_transition_a_remap_and_the_archive_marker_set_their_columns():
    row = replay(
        _events(
            CREATED,
            ("Claimed", {"assignee": "s-1"}),
            ("Transitioned", {"to": "In Progress"}),
            ("Remapped", {"mapping": {"In Progress": "Doing"}}),
            ("Archived", {}),
        )
    )
    assert (row["assignee"], row["state"], row["archived"]) == ("s-1", "Doing", True)

    row = fold(row, replace(_events(("Rehydrated", {}))[0], version=6))
    assert (row["archived"], row["version"]) == (False, 6)


def test_a_released_task_has_no_assignee_and_a_refused_claim_changes_nothing_but_the_version():
    row = replay(_events(CREATED, ("Claimed", {"assignee": "s-1"}), ("ClaimRefused", {"holder": "s-1"}), ("Released", {})))

    assert row["assignee"] == ""
    assert row["version"] == 4


def test_a_comment_is_appended_and_an_import_sets_the_whole_task():
    row = replay(
        _events(
            ("TaskImported", {"title": "Old", "state": "Done", "archived": True, "criteria": [{"kind": "done", "n": 1, "text": "d", "checked": True, "evidence": ""}]}),
            ("CommentAdded", {"text": "hi"}),
        )
    )

    assert (row["title"], row["state"], row["archived"]) == ("Old", "Done", True)
    assert row["criteria"][0]["checked"] is True
    assert row["comments"] == [{"at": 102.0, "actor": "adin", "text": "hi"}]


def test_an_event_type_the_fold_does_not_know_is_refused():
    with pytest.raises(UnknownEvent, match="Teleported"):
        replay(_events(CREATED, ("Teleported", {})))
