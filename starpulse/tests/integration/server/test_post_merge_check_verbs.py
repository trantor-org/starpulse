"""The verdict and miss verbs: a check's verdict lands on its task as a comment, and a miss files its fix with it or not at all."""

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.board import native
from starpulse._internal.board.seam import Board, Written
from starpulse._internal.cli import agent_cli as cli
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import serve, task, url
from starpulse.tests.fake_board import bare_board
from starpulse.tests.machines import MACHINES
from starpulse.tests.unit.board.test_native import native_root, write_task

CHECK = "  - {{id: {id}, text: It answers, within: 1d, pass: {{kind: prom, expr: up}}}}"
BLOCK = "Why\n\n## Post-merge Checks\n\n```yaml\npost_merge_checks:\n" + "\n".join(
    CHECK.format(id=i) for i in ("live", "other")
)
MISS = {
    "task": "task-1",
    "check": "live",
    "fix": {"title": "Repair live", "description": "It was down"},
    "evidence": "up=0",
}
VERDICT = {"task": "task-1", "check": "live", "verdict": "pass", "evidence": "up=1"}


@dataclass
class Served:
    url: str
    built: Board
    base: Path

    def post(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            f"{self.url}{path}", json.dumps(body).encode(), {"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def comments(self, task_id: str = "task-1") -> list[str]:
        assert self.built.read is not None
        return [comment["text"] for comment in (self.built.read(task_id) or {})["comments"]]

    def open_tasks(self) -> int:
        return len(list(native_root(self.base).glob("tasks/*.md")))


@contextmanager
def _served(tmp_path: Path, description: str = BLOCK + "\n```\n", **seams: Callable[..., Written]) -> Iterator[Served]:
    """A server over a native board holding `task-1` (In Progress, with `description`) and `task-2`; `seams` replace writers."""
    native.board({}, tmp_path)
    for number in (1, 2):
        write_task(tmp_path, f"task-{number}", "In Progress")
    first = next(native_root(tmp_path).glob("tasks/task-1 *.md"))
    first.write_text(first.read_text().replace("Why\n", description, 1))
    built = native.board({}, tmp_path)
    feed = BoardFeed(machines=MACHINES)
    for number in (1, 2):
        feed.put(task(f"task-{number}", "In Progress"))
    writers = {"read": built.read, "edit": built.edit, "archive": built.archive, "create": built.create, **seams}
    with serve(tmp_path, feed, bare_board(**writers)) as server:
        yield Served(url(server, ""), built, tmp_path)


def test_a_pass_verdict_is_recorded_as_a_comment_on_the_task(tmp_path: Path) -> None:
    with _served(tmp_path) as served:
        status, reply = served.post("/api/verdict", VERDICT)

        assert (status, reply) == (200, {"task": "task-1", "check": "live", "verdict": "PASS"})
        assert served.comments() == ["[post-merge-check] live PASS\nup=1"]


def test_a_verdict_is_final_so_a_second_one_for_the_check_is_refused(tmp_path: Path) -> None:
    with _served(tmp_path) as served:
        served.post("/api/verdict", VERDICT)
        status, reply = served.post("/api/verdict", {**VERDICT, "verdict": "miss", "fix": "task-2"})

        assert status == 409
        assert "already has a PASS verdict" in reply["error"]
        assert len(served.comments()) == 1


def test_a_check_the_task_does_not_declare_takes_no_verdict(tmp_path: Path) -> None:
    with _served(tmp_path) as served:
        status, reply = served.post("/api/verdict", {**VERDICT, "check": "nope"})

        assert status == 409
        assert "declares no post-merge check 'nope'" in reply["error"]
        assert served.comments() == []


def test_a_malformed_block_takes_no_verdict_and_the_refusal_says_why(tmp_path: Path) -> None:
    broken = BLOCK.replace("within: 1d", "within: soon", 1) + "\n```\n"
    with _served(tmp_path, broken) as served:
        status, reply = served.post("/api/verdict", VERDICT)

        assert status == 409
        assert "post-merge check live: within 'soon'" in reply["error"]
        assert served.comments() == []


@pytest.mark.parametrize(
    "change",
    [{"verdict": "maybe"}, {"verdict": "miss"}, {"check": ""}, {"evidence": 5}, {"task": None}],
)
def test_a_verdict_request_that_is_malformed_writes_nothing(tmp_path: Path, change: dict[str, Any]) -> None:
    with _served(tmp_path) as served:
        status, _ = served.post("/api/verdict", {**VERDICT, **change})

        assert status == 400
        assert served.comments() == []


def test_a_miss_verdict_names_a_fix_task_the_board_holds(tmp_path: Path) -> None:
    with _served(tmp_path) as served:
        missing, _ = served.post("/api/verdict", {**VERDICT, "verdict": "miss", "fix": "task-9"})
        status, reply = served.post("/api/verdict", {**VERDICT, "verdict": "miss", "fix": "task-2"})

        assert (missing, status) == (404, 200)
        assert reply["fix"] == "task-2"
        assert served.comments() == ["[post-merge-check] live MISS\nFix: task-2\nup=1"]


def test_a_miss_files_the_fix_and_records_the_verdict_naming_it(tmp_path: Path) -> None:
    with _served(tmp_path) as served:
        status, reply = served.post("/api/miss", MISS)

        fix = reply["fix"]
        assert (status, reply["verdict"], reply["task"]) == (200, "MISS", "task-1")
        assert served.comments() == [f"[post-merge-check] live MISS\nFix: {fix}\nup=0"]
        assert served.open_tasks() == 3
        assert (served.built.read or (lambda _: None))(fix)["title"] == "Repair live"


def test_a_miss_the_board_refuses_to_record_leaves_no_fix_behind(tmp_path: Path) -> None:
    def refusing_edit(*_: Any, **__: Any) -> Written:
        return Written(False, "refused")

    with _served(tmp_path, edit=refusing_edit) as served:
        status, reply = served.post("/api/miss", MISS)

        assert (status, reply["error"]) == (409, "refused")
        assert served.open_tasks() == 2
        assert served.comments() == []


def test_a_miss_whose_fix_the_board_refuses_to_file_records_no_verdict(tmp_path: Path) -> None:
    def refusing_create(*_: Any, **__: Any) -> Written:
        return Written(False, "refused")

    with _served(tmp_path, create=refusing_create) as served:
        status, reply = served.post("/api/miss", MISS)

        assert (status, reply["error"]) == (409, "refused")
        assert served.open_tasks() == 2
        assert served.comments() == []


@pytest.mark.parametrize("change", [{"check": "nope"}, {"check": "other", "fix": {}}, {"fix": "task-2"}])
def test_a_miss_that_cannot_be_recorded_files_no_fix(tmp_path: Path, change: dict[str, Any]) -> None:
    with _served(tmp_path) as served:
        served.post("/api/verdict", {**VERDICT, "check": "live"})
        status, _ = served.post("/api/miss", {**MISS, **change})

        assert status in (400, 409)
        assert served.open_tasks() == 2
        assert len(served.comments()) == 1


def test_the_cli_records_a_verdict_and_a_miss_as_the_agent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with _served(tmp_path) as served:
        passed = cli.main(
            ["task", "verdict", "task-1", "live", "pass", "--evidence", "up=1", "--server", served.url], {}
        )
        first = json.loads(capsys.readouterr().out)
        missed = cli.main(["task", "miss", "task-1", "other", "--title", "Repair other", "--server", served.url], {})
        second = json.loads(capsys.readouterr().out)
        again = cli.main(["task", "verdict", "task-1", "live", "pass", "--server", served.url], {})
        refused = json.loads(capsys.readouterr().out)

        assert (passed, missed, again) == (0, 0, 1)
        assert (first["verdict"], second["verdict"]) == ("PASS", "MISS")
        assert "already has a PASS verdict" in refused["error"]
        assert served.comments()[1].startswith(f"[post-merge-check] other MISS\nFix: {second['fix']}")
