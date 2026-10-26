"""A `[board] guards` rule refuses the same move with the same reason from an agent's CLI and from the page."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.cli import agent_cli as cli
from starpulse.board.adapters import native
from starpulse.board.board_feed import BoardFeed
from starpulse.contracts.adapters import Move
from starpulse.runtime.adapter_kit import serve, task, url
from starpulse.tests.machines import MACHINES, ROLES
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
    built = native.board({"guards": rules}, tmp_path)
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("task-1", "In Progress", moves={"done": Move(allowed=True)}))
    with serve(tmp_path, feed, built) as server:
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


def _batch_move(server: str, tasks: list[str], to: str) -> tuple[int, dict[str, Any]]:
    """The page's move of each of `tasks` to `to` in one request, the way the agent CLI names several."""
    post = urllib.request.Request(
        f"{server}/api/move",
        data=json.dumps({"tasks": tasks, "to": to}).encode(),
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


def test_a_batch_move_answers_each_task_with_its_own_verdict(tmp_path: Path) -> None:
    native.board({}, tmp_path)
    write_task(tmp_path, "task-1", "In Progress")
    write_task(tmp_path, "task-2", "In Progress")
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("task-1", "In Progress", moves={"done": Move(allowed=True)}))
    feed.put(task("task-2", "In Progress", moves={}))
    with serve(tmp_path, feed, native.board({}, tmp_path)) as server:
        status, body = _batch_move(url(server, ""), ["task-1", "task-2"], "done")

    assert status == 200
    assert body["moved"] == ["task-1"]
    assert list(body["refused"]) == ["task-2"]


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


def _batch_create(server: str, specs: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
    """The agent CLI's create of each of `specs` in one request."""
    post = urllib.request.Request(
        f"{server}/api/tasks",
        data=json.dumps({"tasks": specs}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(post, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _serve_creates(tmp_path: Path, settings: dict[str, Any]) -> Any:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    return serve(tmp_path, feed, native.board(settings, tmp_path))


def _task_texts(tmp_path: Path) -> list[str]:
    return [path.read_text() for path in sorted((native_root(tmp_path) / "tasks").glob("*.md"))]


def test_a_batch_create_makes_every_accepted_task_in_one_request(tmp_path: Path) -> None:
    with _serve_creates(tmp_path, {}) as server:
        status, body = _batch_create(url(server, ""), [{"title": "One"}, {"title": "Two"}, {"title": "Three"}])

    assert status == 200
    assert [result["task"] for result in body["results"]] == [f"task-{n}" for n in (1, 2, 3)]
    assert len(_task_texts(tmp_path)) == 3


def test_a_refused_spec_in_a_batch_create_leaves_the_others_created(tmp_path: Path) -> None:
    with _serve_creates(tmp_path, {"types": ["bug"]}) as server:
        specs = [{"title": "One", "type": "bug"}, {"title": "Two", "type": "nope"}, {"title": "Three", "type": "bug"}]
        status, body = _batch_create(url(server, ""), specs)

    assert status == 200
    one, two, three = body["results"]
    assert "task" in one
    assert "nope" in two["error"]
    assert "task" in three
    assert len(_task_texts(tmp_path)) == 2


def test_a_batch_create_resolves_a_dependency_on_a_sibling_to_its_new_id(tmp_path: Path) -> None:
    with _serve_creates(tmp_path, {}) as server:
        specs = [{"title": "First", "ref": "a"}, {"title": "Second", "dependencies": ["ref:a"]}]
        status, body = _batch_create(url(server, ""), specs)

    assert status == 200
    first, second = (result["task"] for result in body["results"])
    assert f"- {first}\n" in _task_texts(tmp_path)[1]


def test_the_cli_batch_create_names_each_refused_spec_and_exits_non_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    specs = tmp_path / "specs.json"
    specs.write_text(json.dumps([{"title": "One", "type": "bug"}, {"title": "Two", "type": "nope"}]))
    with _serve_creates(tmp_path, {"types": ["bug"]}) as server:
        code = cli.main(["task", "create", "--batch", str(specs), "--server", url(server, "")], {})

    out = json.loads(capsys.readouterr().out)
    assert code != 0
    assert out["created"] == ["task-1"]
    assert list(out["refused"]) == ["2"]
