"""What the reconcile pass makes of the lists GitHub returns."""

from __future__ import annotations

from starpulse.github.model.events import facts_of
from starpulse.github.model.reconcile import pull_delivery, redeliveries, suite_delivery

HEAD = "a" * 40
MERGE = "b" * 40


def test_the_newest_attempt_of_each_absent_guid_is_redelivered_unless_a_redelivery_exists() -> None:
    attempts = [
        {"id": 1, "guid": "lost", "delivered_at": "2026-11-06T12:00:00Z", "redelivery": False},
        {"id": 2, "guid": "lost", "delivered_at": "2026-11-06T12:10:00Z", "redelivery": False},
        {"id": 3, "guid": "again", "delivered_at": "2026-11-06T12:00:00Z", "redelivery": False},
        {"id": 4, "guid": "again", "delivered_at": "2026-11-06T12:20:00Z", "redelivery": True},
        {"id": 5, "guid": "held", "delivered_at": "2026-11-06T12:30:00Z", "redelivery": False},
    ]

    assert redeliveries(attempts, {"held"}) == [2]


def test_a_closed_pull_request_unmerged_is_keyed_by_its_head_and_an_open_one_has_no_row() -> None:
    closed = {"number": 4, "state": "closed", "merged_at": None, "merge_commit_sha": None, "head": {"sha": HEAD}}
    opened = {**closed, "state": "open"}

    delivery = pull_delivery("acme/widgets", closed)

    assert delivery is not None
    assert delivery.delivery_id == f"reconcile:acme/widgets:4:{HEAD}"
    assert [(fact.event, fact.key) for fact in facts_of(delivery.event, delivery.body)] == [("PR_CLOSED", HEAD)]
    assert pull_delivery("acme/widgets", opened) is None


def test_a_suite_still_running_has_no_row() -> None:
    running = {"id": 9, "status": "in_progress", "conclusion": None}
    passed = {"id": 9, "status": "completed", "conclusion": "success"}

    assert suite_delivery("acme/widgets", 4, HEAD, running) is None
    delivery = suite_delivery("acme/widgets", 4, HEAD, passed)
    assert delivery is not None
    assert [(fact.event, fact.key) for fact in facts_of(delivery.event, delivery.body)] == [("CHECKS_PASSED", "9")]
