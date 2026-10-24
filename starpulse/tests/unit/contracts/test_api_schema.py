"""The API schema lists the held task's `skill` and `interactive` fields on the task body every board view shares."""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA = Path(__file__).parents[3] / "api.schema.json"


def test_the_raw_task_body_lists_the_skill_and_interactive_fields() -> None:
    properties = json.loads(SCHEMA.read_text())["$defs"]["RawTask"]["properties"]
    assert {"skill", "interactive"} <= properties.keys()
