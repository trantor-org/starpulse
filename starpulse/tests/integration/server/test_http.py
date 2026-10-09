"""What the running server hands a browser."""

import http.client
import json
import mimetypes
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from starpulse._internal.board.seam import Written
from starpulse._internal.server import server as server_module
from starpulse._internal.kit.adapter_kit import next_event as _next_event
from starpulse._internal.kit.adapter_kit import serve as _serve
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.kit.adapter_kit import url as _url
from starpulse.contracts.adapters import Move
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.feed.machine_tasks import MachineTasks
from starpulse._internal.config.config import CommitKeys
from starpulse.tests.machines import MACHINES

RUN_SAFE = frozenset({"dagu/whole-repo-gate"})


@pytest.fixture
def server(tmp_path: Path) -> Iterator[ThreadingHTTPServer]:
    with _serve(tmp_path, BoardFeed(machines=MACHINES)) as server:
        yield server


#: The host's mime table names JavaScript one of two ways (a runner's /etc/mime.types may say application/javascript).
_JAVASCRIPT = "application/javascript"


def _status(server: ThreadingHTTPServer, path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(_url(server, path), timeout=5) as resp:
            kind = resp.headers.get_content_type()
            return resp.status, "text/javascript" if kind == _JAVASCRIPT else kind
    except urllib.error.HTTPError as exc:
        return exc.code, ""


def test_the_build_is_served_and_nothing_outside_it(server: ThreadingHTTPServer) -> None:
    paths = (
        "/",
        "/?demo",
        "/board",
        "/runs",
        "/flow/authoring-skills",
        "/flow/nope",
        "/flow/board",
        "/assets/index-abc123.js",
        "/assets/",
        "/../secret.txt",
        "/missing.js",
    )

    # The stdlib handler reads the host's mime table: a host that maps .js to the legacy
    # application/javascript serves the same script, so both spellings are one type here.
    legacy_js = {"application/javascript": "text/javascript"}
    served = {path: (code, legacy_js.get(kind, kind)) for path, (code, kind) in ((p, _status(server, p)) for p in paths)}

    assert served == {
        "/": (200, "text/html"),
        "/?demo": (200, "text/html"),
        "/board": (200, "text/html"),
        "/runs": (200, "text/html"),
        "/flow/authoring-skills": (200, "text/html"),
        "/flow/nope": (404, ""),
        "/flow/board": (404, ""),  # the Board is drawn at /board
        "/assets/index-abc123.js": (200, "text/javascript"),
        "/assets/": (404, ""),
        "/../secret.txt": (404, ""),
        "/missing.js": (404, ""),
    }


def test_a_script_is_text_javascript_on_a_host_whose_mime_table_says_otherwise(
    server: ThreadingHTTPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = mimetypes.guess_file_type
    monkeypatch.setattr(
        mimetypes,
        "guess_file_type",
        lambda path, *, strict=True: ("application/javascript", None)
        if str(path).endswith(".js")
        else host(path, strict=strict),
    )

    assert _status(server, "/assets/index-abc123.js") == (200, "text/javascript")


def test_the_snapshot_endpoint_is_the_document_the_event_stream_connects_with(tmp_path: Path) -> None:
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-1", "To Do", milestone="m-76"))
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/snapshot"), timeout=5) as resp:
            polled = (resp.status, resp.headers["Content-Type"], resp.headers["Cache-Control"], json.load(resp))
        with urllib.request.urlopen(_url(server, "/api/events"), timeout=5) as resp:
            _, streamed = _next_event(resp)

    status, content_type, cache, document = polled
    assert (status, content_type, cache) == (200, "application/json", "no-store")
    assert document.pop("now") <= streamed.pop("now")  # read a moment apart, so only the clock differs
    assert document == streamed
    assert [a["id"] for a in document["flows"][0]["agents"]] == ["PROJ-1"]


def test_the_first_event_carries_each_open_tasks_milestone(tmp_path: Path) -> None:
    feed = BoardFeed()
    feed.put(task("PROJ-1", milestone="m-76"))
    feed.put(task("PROJ-2"))
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/events"), timeout=5) as resp:
            first = _next_event(resp)

    name, snapshot = first
    assert name == "snapshot"
    assert {a["id"]: a["milestone"] for a in snapshot["flows"][0]["agents"]} == {"PROJ-1": "m-76", "PROJ-2": ""}


#: A workflow as the page reads it: the API refuses a body short of a field its model names.
_DAG = {"name": "d", "status": "succeeded", "runId": "1", "startedAt": "", "finishedAt": "", "steps": []}


def _machine_fields(task: str) -> dict:
    return {"machine": "in-progress", "event": "WORKTREE_READY", "task": task, "time": str(time.time())}


def test_the_event_stream_sends_a_snapshot_then_a_delta_per_change(tmp_path: Path) -> None:
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/events"), timeout=5) as resp:
            head = (resp.status, resp.headers["Content-Type"], resp.headers["Cache-Control"])
            first = _next_event(resp)
            feed.put(task("PROJ-1", "In Progress"))
            second = _next_event(resp)
            feed.set_dags("ci", [_DAG], None)
            third = _next_event(resp)
            MachineTasks(feed).handle_entry("1-0", _machine_fields("PROJ-1"))
            fourth = _next_event(resp)

    assert head == (200, "text/event-stream", "no-store")
    assert first[0] == "snapshot"
    assert [(a["id"], a["state"]) for a in first[1]["flows"][0]["agents"]] == [("PROJ-1", "to_do")]
    assert second[0] == "task"
    assert (second[1]["id"], second[1]["agent"]["state"], second[1]["settled"]) == ("PROJ-1", "in_progress", None)
    assert (third[0], [d["name"] for d in third[1]["dags"]]) == ("dags", ["ci/d"])
    assert (fourth[0], fourth[1]["flow"], fourth[1]["id"], fourth[1]["agent"]["state"]) == (
        "move",
        "in-progress",
        "PROJ-1",
        "worktree_ready",
    )


def test_a_change_is_encoded_once_however_many_pages_are_streaming(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    encoded: list[str] = []
    encode_event = server_module.event
    monkeypatch.setattr(server_module, "event", lambda name, data: encoded.append(name) or encode_event(name, data))
    feed = BoardFeed()
    with _serve(tmp_path, feed) as server:
        with (
            urllib.request.urlopen(_url(server, "/api/events"), timeout=5) as one,
            urllib.request.urlopen(_url(server, "/api/events"), timeout=5) as other,
        ):
            _next_event(one)
            _next_event(other)
            feed.set_dags("ci", [_DAG], None)
            seen = [_next_event(one), _next_event(other)]

    assert [name for name, _ in seen] == ["dags", "dags"]
    assert seen[0][1] == seen[1][1]
    assert encoded == ["dags"]


def test_an_idle_event_stream_sends_a_comment_so_a_dead_page_is_noticed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("starpulse._internal.server.server._PING_S", 0.05)
    with _serve(tmp_path) as server:
        with urllib.request.urlopen(_url(server, "/api/events"), timeout=5) as resp:
            lines = [resp.readline() for _ in range(5)]

    assert b": ping\n" in lines


def test_a_page_that_goes_away_is_unsubscribed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse._internal.server.server._PING_S", 0.05)
    feed = BoardFeed()
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/events"), timeout=5) as resp:
            _next_event(resp)
            assert len(feed._subscribers) == 1
        deadline = time.monotonic() + 5
        while feed._subscribers and time.monotonic() < deadline:
            time.sleep(0.02)

    assert feed._subscribers == []


def test_a_run_is_started_by_post_and_never_by_get(tmp_path: Path) -> None:
    sent: list[str] = []

    def start(workflow: str) -> str:
        sent.append(workflow)
        return "run-7"

    with _serve(tmp_path, starts={"dagu": start}, run_safe=RUN_SAFE) as server:
        with pytest.raises(urllib.error.HTTPError) as got:
            urllib.request.urlopen(_url(server, "/api/run/dagu/whole-repo-gate"), timeout=5)
        request = urllib.request.Request(_url(server, "/api/run/dagu/whole-repo-gate"), data=b"", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as resp:
            posted = (resp.status, resp.headers.get_content_type(), json.load(resp))

    assert (got.value.code, got.value.headers["Allow"]) == (405, "POST")
    assert posted == (200, "application/json", {"runId": "run-7"})
    assert sent == ["whole-repo-gate"]


class _Failing(BoardFeed):
    """A feed whose workflow has one unresolved failure, started with a known commit."""

    def commit_keys(self, instance: str) -> CommitKeys:
        return CommitKeys(after="AFTER", force="FORCE")

    def open_failure(self, dag: str) -> dict:
        return {"runId": "r-bad", "params": {"AFTER": "a" * 40}}


def test_a_forced_rerun_is_started_by_post_and_never_by_get_through_the_reruns_path(tmp_path: Path) -> None:
    sent: list[tuple[str, dict]] = []

    def rerun(workflow: str, params: dict) -> str:
        sent.append((workflow, params))
        return "run-8"

    with _serve(tmp_path, feed=_Failing(machines=MACHINES), reruns={"dagu": rerun}, run_safe=RUN_SAFE) as server:
        path = "/api/runs/dagu/whole-repo-gate/rerun"
        with pytest.raises(urllib.error.HTTPError) as got:
            urllib.request.urlopen(_url(server, path), timeout=5)
        request = urllib.request.Request(_url(server, path), data=b"", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as resp:
            posted = (resp.status, json.load(resp))
        plain = urllib.request.Request(_url(server, path), data=b"", headers={"Content-Type": "text/plain"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as foreign:
            urllib.request.urlopen(plain, timeout=5)

    assert (got.value.code, got.value.headers["Allow"]) == (405, "POST")
    assert posted == (200, {"runId": "run-8"})
    assert sent == [("whole-repo-gate", {"FORCE": "1", "AFTER": "a" * 40})]
    assert foreign.value.code == 415


def test_a_refused_run_answers_json_with_its_status(tmp_path: Path) -> None:
    with _serve(tmp_path, starts={"dagu": lambda workflow: "run-7"}) as server:
        request = urllib.request.Request(_url(server, "/api/run/dagu/board-autopilot"), data=b"", headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request, timeout=5)

    assert refused.value.code == 404
    assert json.load(refused.value) == {"error": "dagu/board-autopilot is not declared run-safe"}


def test_post_run_answers_404_for_an_adapter_without_start_and_a_run_id_for_a_run_safe_workflow_on_one_with_it(
    tmp_path: Path,
) -> None:
    def post(server: ThreadingHTTPServer) -> tuple[int, dict]:
        request = urllib.request.Request(_url(server, "/api/run/dagu/whole-repo-gate"), data=b"", headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    starts = {"dagu": lambda workflow: f"{workflow}-1"}
    with (
        _serve(tmp_path, run_safe=RUN_SAFE) as without,
        _serve(tmp_path, starts=starts, run_safe=RUN_SAFE) as with_start,
    ):
        answers = post(without), post(with_start)

    assert answers == (
        (404, {"error": "no adapter can start dagu/whole-repo-gate"}),
        (200, {"runId": "whole-repo-gate-1"}),
    )


def test_a_dag_absent_from_the_configs_run_safe_list_answers_404_on_post(tmp_path: Path) -> None:
    """`whole-repo-gate` is a DAG trantor runs, so only the config can be what refuses it here."""
    with _serve(tmp_path, starts={"dagu": lambda workflow: "run-7"}, run_safe=frozenset({"dagu/nightly"})) as server:
        request = urllib.request.Request(_url(server, "/api/run/dagu/whole-repo-gate"), data=b"", headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request, timeout=5)

    assert refused.value.code == 404
    assert json.load(refused.value) == {"error": "dagu/whole-repo-gate is not declared run-safe"}


def test_a_post_anywhere_but_the_run_endpoint_is_not_found(server: ThreadingHTTPServer) -> None:
    request = urllib.request.Request(_url(server, "/api/snapshot"), data=b"", method="POST")

    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=5)

    assert refused.value.code == 404


def _post_move(server: ThreadingHTTPServer, body: dict) -> tuple[int, dict]:
    request = urllib.request.Request(_url(server, "/api/move"), data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def test_a_move_posted_with_no_content_length_is_an_empty_body_not_a_wait_for_bytes(tmp_path: Path) -> None:
    with _serve(tmp_path) as server:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.putrequest("POST", "/api/move")
        connection.putheader("Content-Type", "application/json")
        connection.endheaders()
        response = connection.getresponse()
        body = json.load(response)
        connection.close()

    assert response.status == 400
    assert "a move needs" in body["error"]


def test_a_move_posted_to_the_server_reaches_the_writer_and_answers_json(tmp_path: Path) -> None:
    sent: list[tuple[str, str]] = []
    actors: list[str] = []

    def writer(task: str, status: str, actor: str) -> Written:
        sent.append((task, status))
        actors.append(actor)
        return Written(True, "ok") if status == "In Progress" else Written(False, "refused: Run the `x` skill", "x")

    feed = BoardFeed()
    feed.put(task("PROJ-3", "Ready", moves={"in_progress": Move(allowed=True), "waiting": Move(allowed=True)}))
    with _serve(tmp_path, feed, writer=writer) as server:
        allowed = _post_move(server, {"task": "PROJ-3", "to": "in_progress"})
        refused = _post_move(server, {"task": "PROJ-3", "to": "waiting"})
        with pytest.raises(urllib.error.HTTPError) as got:
            urllib.request.urlopen(_url(server, "/api/move"), timeout=5)

    assert allowed == (200, {"task": "PROJ-3", "to": "in_progress"})
    assert refused == (409, {"error": "refused: Run the `x` skill", "skill": "x"})
    assert (got.value.code, got.value.headers["Allow"]) == (405, "POST")
    assert sent == [("PROJ-3", "In Progress"), ("PROJ-3", "Waiting")]
    assert actors == ["operator", "operator"]  # the page names no actor, so it writes as the operator


def test_a_start_posted_to_the_server_saves_the_assignee_starts_the_session_and_answers_json(tmp_path: Path) -> None:
    assigned: list[tuple[str, str]] = []
    started: list[str] = []

    def assign(task: str, assignee: str) -> Written:
        assigned.append((task, assignee))
        return Written(True, "ok")

    def start_session(task: str) -> str:
        started.append(task)
        return "https://claude.ai/code/session_01"

    feed = BoardFeed()
    feed.put(task("PROJ-3", "Ready"))
    body = json.dumps({"task": "PROJ-3", "assignee": "@agent-deep-high"}).encode()
    with _serve(tmp_path, feed, assign=assign, start_session=start_session) as server:
        request = urllib.request.Request(_url(server, "/api/start"), data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as resp:
            answered = resp.status, json.load(resp)
        with pytest.raises(urllib.error.HTTPError) as got:
            urllib.request.urlopen(_url(server, "/api/start"), timeout=5)

    assert answered[0] == 200
    assert {k: answered[1][k] for k in ("task", "url")} == {
        "task": "PROJ-3",
        "url": "https://claude.ai/code/session_01",
    }
    assert (assigned, started) == ([("PROJ-3", "@agent-deep-high")], ["PROJ-3"])
    assert (got.value.code, got.value.headers["Allow"]) == (405, "POST")


def _post(server: ThreadingHTTPServer, path: str, body: dict) -> tuple[int, dict]:
    request = urllib.request.Request(_url(server, path), data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def test_a_task_is_read_edited_and_archived_through_the_server(tmp_path: Path) -> None:
    record = {"title": "t", "plan": "1. do it"}
    sent: list[tuple[str, dict, str]] = []
    archived: list[tuple[str, str]] = []

    def edit(task: str, changes: dict, comment: str) -> Written:
        sent.append((task, changes, comment))
        record.update(changes)
        return Written(True, "ok")

    def archive(task: str, reason: str) -> Written:
        archived.append((task, reason))
        return Written(True, "ok")

    feed = BoardFeed()
    feed.put(task("PROJ-3", "Ready"))
    with _serve(tmp_path, feed, read=lambda _: dict(record), edit=edit, archive=archive) as server:
        with urllib.request.urlopen(_url(server, "/api/task/PROJ-3"), timeout=5) as resp:
            opened = json.load(resp)
        record["plan"] = "another writer's plan"
        stale = _post(server, "/api/edit", {"task": "PROJ-3", "base": opened["record"], "changes": {"plan": "mine"}})
        saved = _post(server, "/api/edit", {"task": "PROJ-3", "base": dict(record), "changes": {"title": "u"}})
        gone = _post(server, "/api/archive", {"task": "PROJ-3", "reason": "obsolete"})
        with pytest.raises(urllib.error.HTTPError) as got:
            urllib.request.urlopen(_url(server, "/api/edit"), timeout=5)

    assert opened == {"task": "PROJ-3", "record": {"title": "t", "plan": "1. do it"}}
    assert stale[0] == 409
    assert stale[1]["stale"] == ["plan"]
    assert saved == (200, {"task": "PROJ-3", "changed": ["title"]})
    assert sent == [("PROJ-3", {"title": "u"}, "")]
    assert gone == (200, {"task": "PROJ-3"})
    assert archived == [("PROJ-3", "obsolete")]
    assert (got.value.code, got.value.headers["Allow"]) == (405, "POST")


def test_the_page_script_is_served_as_text_javascript_whatever_the_hosts_mime_table_says(
    server: ThreadingHTTPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(mimetypes.types_map, ".js", "application/javascript")  # what a runner's /etc/mime.types gives

    assert _status(server, "/assets/index-abc123.js") == (200, "text/javascript")
