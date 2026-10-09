"""A `[board] rules` rule refuses the same move with the same reason from an agent's CLI and from the page."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.board import native
from starpulse._internal.cli import agent_cli as cli
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import serve, task, url
from starpulse.contracts.adapters import Move
from starpulse.tests.machines import MACHINES
from starpulse.tests.unit.board.test_native import native_root, write_task

NEEDS_PR = {
    "on": {"to": "Done"},
    "require": {"field": {"field": "references", "matches": r"/pull/\d+$", "min": 1}},
    "reason": "Done needs a pull request in references",
    "skill": "completing-tasks",
}
REFUSED = {"error": NEEDS_PR["reason"], "skill": "completing-tasks"}


@contextmanager
def _served(tmp_path: Path, rules: list[dict[str, Any]]) -> Iterator[str]:
    """A server whose board writer is a native board with `rules`, holding `task-1` In Progress with Done offered."""
    native.board({}, tmp_path)
    write_task(tmp_path, "task-1", "In Progress")
    built = native.board({"rules": rules}, tmp_path)
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("task-1", "In Progress", moves={"done": Move(allowed=True)}))
    with serve(tmp_path, feed, writer=built.writer) as server:
        yield url(server, "")


def _page_move(server: str) -> tuple[int, dict[str, Any]]:
    """The page's move of task-1 to Done: it names no actor, so the board writes it as the operator."""
    post = urllib.request.Request(
        f"{server}/api/move",
        data=json.dumps({"task": "task-1", "to": "done"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(post, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _cli_move(server: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    """The agent CLI's move of task-1 to Done, which the server writes as the agent."""
    code = cli.main(["task", "move", "task-1", "done", "--server", server], {})
    return code, json.loads(capsys.readouterr().out)


def test_a_configured_rule_refuses_the_same_move_from_the_cli_and_the_page_with_the_same_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with _served(tmp_path, [NEEDS_PR]) as server:
        task_file = next(native_root(tmp_path).glob("tasks/*.md"))
        before = task_file.read_text()

        code, via_cli = _cli_move(server, capsys)
        status, via_page = _page_move(server)

        assert (code, status) == (1, 409)
        assert via_page == REFUSED
        assert (via_cli["ok"], via_cli["reason"], via_cli["skill"]) == (False, REFUSED["error"], REFUSED["skill"])
        assert task_file.read_text() == before


def test_the_actor_a_move_carries_decides_whether_a_rule_exempts_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exempt_agent = {**NEEDS_PR, "unless_actor": ["agent"]}
    with _served(tmp_path, [exempt_agent]) as server:
        status, refused = _page_move(server)
        code, via_cli = _cli_move(server, capsys)

    assert (status, refused) == (409, REFUSED)
    assert (code, via_cli["ok"]) == (0, True)
    assert "status: Done\n" in next(native_root(tmp_path).glob("tasks/*.md")).read_text()
