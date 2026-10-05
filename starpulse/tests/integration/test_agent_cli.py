"""`starpulse snapshot|board|task show|help --agent`: an agent reads the running server and gets one JSON document."""

import json
import socket
import urllib.request
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from starpulse import agent_cli as cli
from starpulse import doctor
from starpulse.board_feed import BoardFeed
from starpulse.contracts import Move
from starpulse.tests.hosts import FakeHost
from starpulse.tests.machines import MACHINES
from starpulse.tests.serving import serve as _serve
from starpulse.tests.serving import url as _url
from starpulse.tests.tasks import task

PULL = "https://github.com/acme/app/pull/5"
UNREAD_PULL = "https://github.com/acme/app/pull/9"  # linked from a task, but the server has not read it


def _run(
    capsys: pytest.CaptureFixture[str], argv: Sequence[str], environ: dict[str, str] | None = None
) -> tuple[int, Any]:
    """The exit code and the one JSON document on stdout; a second document, or any stderr, fails the test."""
    code = cli.main(argv, environ or {})
    out = capsys.readouterr()
    assert out.err == ""
    return code, json.loads(out.out)


@pytest.fixture
def base(tmp_path: Path) -> Iterator[str]:
    """A server's address, its Board holding four open tasks and one completed."""
    feed = BoardFeed(machines=MACHINES)
    feed.put(
        task(
            "PROJ-1",
            "To Do",
            milestone="m-1",
            labels=("cli",),
            assignee="@agent-a",
            dependencies=("PROJ-2", "PROJ-3"),
            references=(PULL, "docs/plan.md"),
            description="Add the verbs.",
            moves={
                "in_progress": Move(allowed=False, reason="claim it first", skill="starting-tasks"),
                "ready": Move(allowed=True),
            },
        )
    )
    feed.put(
        task("PROJ-2", "Ready", milestone="m-2", labels=("api", "cli"), assignee="@agent-b", references=(UNREAD_PULL,))
    )
    feed.put(task("PROJ-3", "Done", settled="completed"))
    feed.put(task("PROJ-4", "In Progress", milestone="m-2", labels=("api",), assignee="@agent-a"))
    feed.put(task("PROJ-5", "Ready"))
    pull = {"number": 5, "url": PULL, "checks": "pass", "merged": False, "threads": 2, "stale": False}
    feed.set_pulls({"PROJ-1": [pull]})
    with _serve(tmp_path, feed) as server:
        yield _url(server, "")


@pytest.fixture(autouse=True)
def healthy_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """`doctor` probes this fake host, not the machine the suite runs on."""
    monkeypatch.setattr(doctor, "LIVE", FakeHost().probes())


def _closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


def test_an_unreachable_server_exits_3_naming_the_url_it_tried(capsys: pytest.CaptureFixture[str]) -> None:
    down = _closed_port_url()

    code, doc = _run(capsys, ["snapshot", "--server", down])

    assert code == 3
    assert doc["code"] == "unavailable"
    assert doc["error"].startswith(f"cannot reach StarPulse at {down}")


def test_a_server_that_answers_an_error_status_is_unavailable_and_named(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["snapshot", "--server", f"{base}/elsewhere"])

    assert code == 3
    assert doc == {
        "error": f"{base}/elsewhere answered 404 for /api/snapshot: is it a StarPulse server?",
        "code": "unavailable",
    }


@pytest.mark.parametrize(
    ("flag", "env", "expected"),
    [
        ("http://flag:1", {"STARPULSE_URL": "http://env:2"}, "http://flag:1"),
        (None, {"STARPULSE_URL": "http://env:2"}, "http://env:2"),
        (None, {}, "http://localhost:8766"),
        ("http://flag:1/", {}, "http://flag:1"),
        ("http://proxy/api-X/", {}, "http://proxy/api-X"),
    ],
)
def test_the_server_is_the_flag_else_the_environment_else_the_default_port(
    flag: str | None, env: dict[str, str], expected: str
) -> None:
    assert cli.server_url(flag, env) == expected


@pytest.mark.parametrize("argv", [["snapshot"], ["board"], ["task", "show", "PROJ-1"]])
def test_a_verb_without_a_server_flag_reads_the_server_the_environment_names(
    base: str, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    code, _ = _run(capsys, argv, {"STARPULSE_URL": base})

    assert code == 0


def test_the_snapshot_verb_prints_the_servers_snapshot(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["snapshot", "--server", base])
    with urllib.request.urlopen(f"{base}/api/snapshot", timeout=5) as resp:
        served = json.load(resp)

    assert code == 0
    assert doc.pop("now") <= served.pop("now")
    assert doc == served


def test_the_board_lists_each_column_with_its_tasks_dependencies_prs_and_moves(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["board", "--server", base])

    assert code == 0
    assert [(c["state"], c["name"], [t["id"] for t in c["tasks"]]) for c in doc["columns"]] == [
        ("to_do", "To Do", ["PROJ-1"]),
        ("ready", "Ready", ["PROJ-2", "PROJ-5"]),
        ("in_progress", "In Progress", ["PROJ-4"]),
        ("review", "Review", []),
        ("done", "Done", []),
    ]
    assert doc["columns"][0]["tasks"][0] == {
        "id": "PROJ-1",
        "title": "Title of PROJ-1",
        "lane": "to_do",
        "assignee": "@agent-a",
        "milestone": "m-1",
        "labels": ["cli"],
        "dependencies": ["PROJ-2", "PROJ-3"],
        "waiting_on": ["PROJ-2"],
        "prs": [{"number": 5, "url": PULL, "checks": "pass", "merged": False, "threads": 2, "stale": False}],
        "moves": {
            "in_progress": {"allowed": False, "reason": "claim it first", "skill": "starting-tasks"},
            "ready": {"allowed": True, "reason": "", "skill": ""},
        },
    }


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (["--state", "ready"], ["PROJ-2", "PROJ-5"]),
        (["--milestone", "m-2"], ["PROJ-2", "PROJ-4"]),
        (["--label", "cli"], ["PROJ-1", "PROJ-2"]),
        (["--assignee", "@agent-a"], ["PROJ-1", "PROJ-4"]),
        (["--milestone", "m-2", "--label", "api", "--assignee", "@agent-a"], ["PROJ-4"]),
        (["--milestone", "m-9"], []),
    ],
)
def test_the_board_keeps_only_the_tasks_every_filter_matches(
    base: str, capsys: pytest.CaptureFixture[str], filters: list[str], expected: list[str]
) -> None:
    code, doc = _run(capsys, ["board", *filters, "--server", base])

    assert code == 0
    assert [t["id"] for c in doc["columns"] for t in c["tasks"]] == expected


def test_a_state_filter_leaves_only_that_column(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    _, doc = _run(capsys, ["board", "--state", "ready", "--server", base])

    assert [c["state"] for c in doc["columns"]] == ["ready"]


def test_a_state_the_board_does_not_have_is_a_usage_error_naming_the_states(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["board", "--state", "nowhere", "--server", base])

    assert (code, doc["code"]) == (2, "usage")
    assert doc["error"] == "unknown state nowhere; the board has to_do, ready, in_progress, review, done"


def test_an_unknown_flag_is_a_usage_error_that_names_it(capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["snapshot", "--nope"])

    assert (code, doc["code"]) == (2, "usage")
    assert "--nope" in doc["error"]


def test_a_pull_request_the_server_has_not_read_is_reported_by_its_link(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _, doc = _run(capsys, ["task", "show", "PROJ-2", "--server", base])

    assert doc["prs"] == [{"url": UNREAD_PULL}]


def test_task_show_gives_the_lane_dependencies_what_it_waits_on_prs_and_moves(
    base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, doc = _run(capsys, ["task", "show", "PROJ-1", "--server", base])

    assert code == 0
    assert doc["lane"] == "to_do"
    assert doc["description"] == "Add the verbs."
    assert doc["dependencies"] == ["PROJ-2", "PROJ-3"]
    assert doc["waiting_on"] == ["PROJ-2"]  # PROJ-3 is completed
    assert doc["prs"][0]["threads"] == 2
    assert doc["moves"]["in_progress"] == {"allowed": False, "reason": "claim it first", "skill": "starting-tasks"}


def test_task_show_reports_a_settled_task_by_where_it_settled(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "show", "PROJ-3", "--server", base])

    assert code == 0
    assert doc == {
        "id": "PROJ-3",
        "title": "",
        "lane": "completed",
        "assignee": "",
        "milestone": "",
        "labels": [],
        "dependencies": [],
        "waiting_on": [],
        "prs": [],
        "moves": {},
        "description": "",
    }


def test_a_task_the_board_does_not_hold_is_not_found(base: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["task", "show", "PROJ-99", "--server", base])

    assert (code, doc["code"]) == (4, "not_found")
    assert "PROJ-99" in doc["error"]


def test_no_verb_is_a_usage_error_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, [])

    assert (code, doc["code"]) == (2, "usage")


def test_the_manifest_lists_each_verbs_arguments_outputs_and_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _run(capsys, ["help", "--agent"])

    assert code == 0
    assert doc["exit_codes"] == {
        "0": "ok",
        "1": "refused or invalid",
        "2": "usage",
        "3": "unavailable",
        "4": "not found",
    }
    board = next(v for v in doc["verbs"] if v["verb"] == "board")
    flags = {flag for arg in board["arguments"] for flag in arg["flags"]}
    assert {"--state", "--milestone", "--label", "--assignee", "--server"} <= flags
    assert board["exit_codes"] == [0, 2, 3]
    assert "columns" in board["outputs"]
    show = next(v for v in doc["verbs"] if v["verb"] == "task show")
    assert [(a["name"], a["required"]) for a in show["arguments"] if not a["flags"]] == [("task", True)]


def test_the_manifest_describes_every_verb_and_each_of_its_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    _, doc = _run(capsys, ["help", "--agent"])

    assert [v["verb"] for v in doc["verbs"]] == ["snapshot", "board", "task show", "doctor", "help"]
    for verb in doc["verbs"]:
        assert verb["summary"]
        assert all(set(a) == {"name", "flags", "required", "help"} for a in verb["arguments"])
        assert all(a["help"] for a in verb["arguments"]), verb["verb"]
        assert "help" not in {a["name"] for a in verb["arguments"]}  # argparse's own -h is not a verb argument
    board = next(v for v in doc["verbs"] if v["verb"] == "board")
    state = next(a for a in board["arguments"] if a["name"] == "state")
    assert (state["flags"], state["required"]) == (["--state"], False)
    manifest = next(v for v in doc["verbs"] if v["verb"] == "help")
    assert [(a["name"], a["flags"], a["required"]) for a in manifest["arguments"]] == [("agent", ["--agent"], True)]


# Every verb the manifest lists, and each exit code it declares, with an argument line that produces it. `{server}`
# is a running server, `{down}` an address nothing listens on.
CASES = {
    ("snapshot", 0): ["snapshot", "--server", "{server}"],
    ("snapshot", 2): ["snapshot", "--nope"],
    ("snapshot", 3): ["snapshot", "--server", "{down}"],
    ("board", 0): ["board", "--server", "{server}"],
    ("board", 2): ["board", "--state", "nowhere", "--server", "{server}"],
    ("board", 3): ["board", "--server", "{down}"],
    ("task show", 0): ["task", "show", "PROJ-1", "--server", "{server}"],
    ("task show", 2): ["task", "show"],
    ("task show", 3): ["task", "show", "PROJ-1", "--server", "{down}"],
    ("task show", 4): ["task", "show", "PROJ-99", "--server", "{server}"],
    ("doctor", 0): ["doctor", "--server", "{server}"],
    ("doctor", 1): ["doctor", "--server", "{down}"],
    ("doctor", 2): ["doctor", "--nope"],
    ("help", 0): ["help", "--agent"],
    ("help", 2): ["help"],
}


def _manifest(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    return _run(capsys, ["help", "--agent"])[1]["verbs"]


def test_every_manifest_verb_and_exit_code_has_a_case(capsys: pytest.CaptureFixture[str]) -> None:
    declared = {(v["verb"], code) for v in _manifest(capsys) for code in v["exit_codes"]}

    assert declared == set(CASES)


@pytest.mark.parametrize(("verb", "exit_code"), list(CASES))
def test_a_manifest_verb_writes_one_json_document_and_exits_as_declared(
    base: str, capsys: pytest.CaptureFixture[str], verb: str, exit_code: int
) -> None:
    manifest = next(v for v in _manifest(capsys) if v["verb"] == verb)
    argv = [a.format(server=base, down=_closed_port_url()) for a in CASES[verb, exit_code]]

    code, doc = _run(capsys, argv)

    assert code == exit_code
    assert exit_code in manifest["exit_codes"]
    # A failed doctor check still reports every check; any other refusal is an error document.
    reports = exit_code == 0 or (verb, exit_code) == ("doctor", 1)
    assert set(doc) == (set(manifest["outputs"]) if reports else {"error", "code"})
