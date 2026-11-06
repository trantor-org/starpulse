"""`TaskKeys.canonical` spells a lower-case key as the scheme names it."""

import re

from starpulse.contracts.task_keys import TaskKeys

KEYS = TaskKeys(
    key=re.compile(r"TASK-\d+"),
    branch=re.compile(r"(?:refs/heads/)?(?:[^/]+/)*?task-(\d+)(?=$|[-_/])", re.I),
    key_format="TASK-{}",
)


def test_lower_case_key_canonicalises() -> None:
    assert KEYS.canonical("task-45") == "TASK-45"


def test_upper_case_key_and_non_key_come_back_as_they_were() -> None:
    assert KEYS.canonical("TASK-45") == "TASK-45"
    assert KEYS.canonical("nothing") == "nothing"
