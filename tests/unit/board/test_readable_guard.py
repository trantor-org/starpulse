"""The `readable` guard primitive refuses a description off its template, naming the broken rule and its line."""

import tempfile
from pathlib import Path
from typing import Any

import pytest
from starpulse.board.adapters.native import board
from starpulse.board.adapters.upstream_backlog import UpstreamBacklog
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model import rules
from starpulse.event_log.event_log import EventLog

from tests.unit.board.test_native import native_root, write_task

#: doc-1035 D1 to D3, the way a project configures the generic primitive.
TEMPLATE: dict[str, Any] = {
    "headings": [
        {"name": "Outcome", "max_sentences": 1},
        {"name": "Why", "max_sentences": 2},
        {"name": "Current State", "max_sentences": 2},
        {"name": "Terms", "optional": True},
        {"name": "Example", "optional": True},
        {"name": "Scope", "no_paths": True},
        {"name": "Out of Scope", "no_paths": True},
        {"name": "Blast Radius"},
        {"name": "Rollback", "optional": True},
        {"name": "Stop Conditions"},
        {"name": "Open Questions", "optional": True},
    ],
    "commands": [
        "uv run",
        "./.venv/bin/",
        "git",
        "rg",
        "starpulse",
        "gh",
        "docker",
        "ssh",
        "make",
        "sudo",
        "systemctl",
    ],
    "max_paths_per_sentence": 2,
    "blast_radius": {"heading": "Blast Radius", "stops": "Stop Conditions", "rollback": "Rollback"},
}
GUARD = {"on": {"write": True}, "require": {"readable": TEMPLATE}, "reason": "The description is not readable"}

GOOD = """## Outcome
A pull request lists its checks.

## Why
Reviewers read checks first. See doc-1020.

## Current State
Checks hide in the log.

## Scope
- Show checks on the card

## Out of Scope
- Rewriting old cards

## Blast Radius
reach 1 · data 0 · undo 0 · detect 0. One module, reverts cleanly.

## Stop Conditions
- The card stops loading
"""


def swapped(old: str, new: str, body: str = GOOD) -> str:
    assert old in body
    return body.replace(old, new)


def verdict(body: str, template: dict[str, Any] = TEMPLATE) -> str:
    return rules.readable_verdict(rules.load([{**GUARD, "require": {"readable": template}}]), {}, body)


def test_a_readable_description_has_an_empty_verdict() -> None:
    assert verdict(GOOD) == ""


@pytest.mark.parametrize(
    ("body", "named"),
    [
        pytest.param(
            swapped("## Why\n", "## Reason\n"), "expected heading `Why`, found `Reason` (line 4)", id="headings"
        ),
        pytest.param(
            swapped("## Scope\n", "## Example\nA before.\n\n## Terms\nA word.\n\n## Scope\n"),
            "expected heading `Scope`, found `Terms` (line 13)",
            id="optional-heading-order",
        ),
        pytest.param(
            swapped("A pull request lists its checks.", "A pull request lists its checks. It also lists reviews."),
            "`Outcome` has 2 sentences, at most 1 (line 2)",
            id="sentence-cap",
        ),
        pytest.param(
            swapped("- Show checks on the card", "- Show checks on the card\n\nuv run pytest tests"),
            "command `uv run` is not in a fenced block (line 13)",
            id="unfenced-command",
        ),
        pytest.param(
            swapped("Checks hide in the log.", "Checks hide in the log of src/app.py."),
            "the path `src/app.py` is not in backticks (line 8)",
            id="unticked-path",
        ),
        pytest.param(
            swapped("Checks hide in the log.", "Checks hide in `a/b/c.py`, `a/b/d.py` and `a/b/e.py`."),
            "a sentence names 3 paths, at most 2: list them (line 8)",
            id="three-paths-in-a-sentence",
        ),
        pytest.param(
            swapped("- Show checks on the card", "- Show checks in `a/b/c.py`"),
            "`Scope` names the path `a/b/c.py` (line 11)",
            id="path-in-scope",
        ),
        pytest.param(
            swapped("reach 1 · data 0 · undo 0 · detect 0.", "reach 4 · data 0 · undo 0 · detect 0."),
            "`Blast Radius` opens with `reach N · data N · undo N · detect N. <sentence>`, each N 0 to 3 (line 17)",
            id="blast-radius-format",
        ),
        pytest.param(
            swapped("reach 1 · data 0", "reach 1 · data 3"),
            "`data` is 3 and no `Stop Conditions` bullet names it (line 19)",
            id="axis-3-stop-condition",
        ),
        pytest.param(
            swapped("undo 0", "undo 2"),
            "`undo` is 2, so a `Rollback` section is required (line 17)",
            id="undo-2-rollback",
        ),
    ],
)
def test_a_readable_option_refuses_its_negative_case_naming_the_rule_and_line(body: str, named: str) -> None:
    assert verdict(body) == named


def test_a_readable_description_names_what_the_axis_3_stop_condition_and_rollback_must_hold() -> None:
    stops = swapped("- The card stops loading", "- The data is lost")
    assert verdict(swapped("reach 1 · data 0", "reach 1 · data 3", stops)) == ""
    rolled = swapped(
        "## Stop Conditions", "## Rollback\nRevert, then rerun.\n\n## Stop Conditions", swapped("undo 0", "undo 2")
    )
    assert verdict(rolled) == ""


def test_a_readable_fence_keeps_a_command_and_a_path_out_of_the_prose_rules() -> None:
    fenced = swapped("- Show checks on the card", "- Show checks on the card\n\n```\nuv run pytest src/app.py\n```")
    assert verdict(fenced) == ""


def test_a_readable_primitive_with_an_unknown_key_or_no_headings_fails_to_load() -> None:
    with pytest.raises(ValueError, match="no key sentences"):
        rules.load([{**GUARD, "require": {"readable": {"headings": [{"name": "Outcome"}], "sentences": 1}}}])
    with pytest.raises(ValueError, match="needs `headings`"):
        rules.load([{**GUARD, "require": {"readable": {}}}])


def test_the_board_refuses_a_create_off_the_template_with_the_rule_and_line_and_writes_nothing(tmp_path: Path) -> None:
    built = board({"guards": [GUARD]}, tmp_path)
    assert built.create is not None

    refused = built.create("Title", {"description": swapped("## Why\n", "## Reason\n")})

    assert not refused.ok
    assert refused.output == "The description is not readable: expected heading `Why`, found `Reason` (line 4)"
    assert refused.lint
    assert not list((native_root(tmp_path) / "tasks").glob("*"))
    assert built.create("Title", {"description": GOOD}).ok


def test_the_template_refuses_task_9251s_current_description_naming_outcome() -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "board" / "task_9251_description.md"
    body = f"<!-- SECTION:DESCRIPTION:BEGIN -->\n{fixture.read_text()}<!-- SECTION:DESCRIPTION:END -->\n"

    found = verdict(body)

    assert "`Outcome`" in found, found


def test_the_snapshot_carries_each_tasks_readable_verdict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval, scanned: (self.scan(), scanned()))
    built = board({"guards": [GUARD]}, tmp_path)
    for name, body in (("task-1", swapped("## Why\n", "## Reason\n")), ("task-2", GOOD)):
        path = write_task(tmp_path, name, "To Do")
        text = path.read_text().replace(
            "Why\n<!-- SECTION:DESCRIPTION:END -->", f"{body}<!-- SECTION:DESCRIPTION:END -->"
        )
        path.write_text(text)
    feed = BoardFeed()
    with tempfile.TemporaryDirectory() as directory:
        built.start(feed, "test", EventLog(f"sqlite:///{Path(directory) / 'events.sqlite'}"))

        snapshot = feed.snapshot()

    by_id = {agent["id"]: agent["readable"] for flow in snapshot["flows"] for agent in flow["agents"]}
    assert by_id == {"task-1": "expected heading `Why`, found `Reason` (line 4)", "task-2": ""}
