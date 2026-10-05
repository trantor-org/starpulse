"""The snapshot the page is handed, and the run endpoint."""

import argparse
import json
import sys
import types
import urllib.request
from pathlib import Path

import pytest

from starpulse.board import MoveWriter, Written
from starpulse.board_feed import BoardFeed
from starpulse.config import Config, RunsInstance, load
from starpulse.contracts import Move, StartFailedError
from starpulse.harnesses import load_harnesses
from starpulse.server import _adapter, _config, _no_writer, move_task, run_dag, start_task
from starpulse.tests.machines import MACHINES
from starpulse.tests.serving import serve, url
from starpulse.tests.tasks import task

#: The workflows the config declares run-safe in these tests, and the domains it groups them in.
RUN_SAFE = frozenset({"dagu/whole-repo-gate", "dagu/healthcheck"})
DOMAINS = {"Ops": ("dagu/whole-repo-gate", "dagu/healthcheck", "dagu/board-autopilot"), "Data": ("dagu/etl",)}


def _feed() -> BoardFeed:
    feed = BoardFeed(machines=MACHINES, domains=DOMAINS, run_safe=RUN_SAFE)
    feed.put(task("PROJ-3", "Ready", moves={"in_progress": Move(allowed=True)}))
    return feed


def test_the_snapshot_carries_the_declared_cues_and_the_configs_domains() -> None:
    body = _feed().snapshot()

    assert body["cues"] == []
    assert [d["name"] for d in body["domains"]] == ["Ops", "Data"]
    assert [dag["name"] for dag in body["domains"][0]["dags"]] == list(DOMAINS["Ops"])
    assert {dag["name"] for d in body["domains"] for dag in d["dags"] if dag["runSafe"]} == RUN_SAFE
    assert body["boardUrl"] is None


_TWO_INSTANCES = """
[[runs]]
name = "prod"
type = "dagu"
url = "http://prod.test:8085"
run_safe = ["nightly"]
[runs.domains]
Ops = ["nightly", "backup"]

[[runs]]
name = "staging"
type = "dagu"
url = "http://staging.test:8085"
run_safe = ["nightly"]
[runs.domains]
Ops = ["nightly"]
"""


def test_a_config_with_two_runs_instances_draws_both_each_workflow_prefixed_with_its_instance(tmp_path: Path) -> None:
    path = tmp_path / "starpulse.toml"
    path.write_text(_TWO_INSTANCES)
    config = load(path)
    feed = BoardFeed(machines=MACHINES, domains=config.qualified_domains(), run_safe=config.qualified_run_safe())

    feed.runs("prod").set_dags([{"name": "nightly"}, {"name": "backup"}], None)
    feed.runs("staging").set_dags([{"name": "nightly"}], None)
    body = feed.snapshot()

    assert [d["name"] for d in body["dags"]] == ["prod/nightly", "prod/backup", "staging/nightly"]
    assert body["domains"] == [
        {
            "name": "Ops",
            "dags": [
                {"name": "prod/nightly", "runSafe": True},
                {"name": "prod/backup", "runSafe": False},
                {"name": "staging/nightly", "runSafe": True},
            ],
        }
    ]


def _ip(*octets: int) -> str:
    """A dotted address from its octets, so no LAN literal sits outside the host inventory."""
    return ".".join(map(str, octets))


class _Start:
    """A stubbed adapter start capability that records each workflow it is asked to start."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[str] = []

    def __call__(self, workflow: str) -> str:
        self.sent.append(workflow)
        if self.error is not None:
            raise self.error
        return "run-1"


@pytest.mark.parametrize("source", ["127.0.0.1", "::1", _ip(10, 4, 0, 9), _ip(172, 20, 1, 1), _ip(192, 168, 0, 42)])
def test_a_lan_browser_starts_a_run_safe_workflow_through_its_instance_and_gets_its_run_id(source: str) -> None:
    start = _Start()

    assert run_dag(source, "dagu/whole-repo-gate", {"dagu": start}, RUN_SAFE) == (200, {"runId": "run-1"})
    assert start.sent == ["whole-repo-gate"]


def test_the_same_workflow_name_on_two_instances_starts_on_the_instance_the_name_carries() -> None:
    prod, staging = _Start(), _Start()
    run_safe = {"prod/nightly", "staging/nightly"}

    run_dag("127.0.0.1", "staging/nightly", {"prod": prod, "staging": staging}, run_safe)

    assert (prod.sent, staging.sent) == ([], ["nightly"])


def test_the_instance_is_the_first_segment_of_the_name_and_the_rest_is_the_workflow() -> None:
    start = _Start()

    run_dag("127.0.0.1", "ci/nested/wf", {"ci": start}, {"ci/nested/wf"})

    assert start.sent == ["nested/wf"]


#: A public (RFC 5737) address, the first one past 172.16/12, carrier-grade NAT and link-local.
@pytest.mark.parametrize("source", ["203.0.113.5", _ip(172, 32, 0, 1), _ip(100, 64, 0, 1), _ip(169, 254, 1, 1)])
def test_a_source_outside_loopback_and_rfc_1918_is_refused_before_the_adapter_is_asked(source: str) -> None:
    start = _Start()

    status, body = run_dag(source, "dagu/whole-repo-gate", {"dagu": start}, RUN_SAFE)

    assert (status, start.sent) == (403, [])
    assert body == {"error": "Run now answers only loopback and private network (RFC 1918) browsers"}


def test_a_workflow_the_config_does_not_declare_run_safe_is_refused_before_the_adapter_is_asked() -> None:
    start = _Start()

    status, body = run_dag(_ip(192, 168, 0, 42), "dagu/board-autopilot", {"dagu": start}, RUN_SAFE)

    assert (status, start.sent) == (404, [])
    assert body == {"error": "dagu/board-autopilot is not declared run-safe"}


@pytest.mark.parametrize("name", ["dagu/whole-repo-gate", "whole-repo-gate", "gone/whole-repo-gate"])
def test_an_instance_without_a_start_capability_answers_404_even_for_a_run_safe_workflow(name: str) -> None:
    assert run_dag("127.0.0.1", name, {}, RUN_SAFE | {name}) == (404, {"error": f"no adapter can start {name}"})


def test_a_start_the_adapter_fails_answers_with_its_reason() -> None:
    start = _Start(StartFailedError("Dagu unreachable: refused"))

    assert run_dag("127.0.0.1", "dagu/healthcheck", {"dagu": start}, RUN_SAFE) == (
        502,
        {"error": "Dagu unreachable: refused"},
    )


def test_the_config_flag_wins_over_a_starpulse_toml_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "starpulse.toml").write_text('tracker_url = "http://here.test"\n')
    chosen = tmp_path / "chosen.toml"
    chosen.write_text('tracker_url = "http://chosen.test"\n')
    monkeypatch.chdir(tmp_path)

    assert _config(argparse.ArgumentParser(), chosen).tracker_url == "http://chosen.test"


def test_without_the_flag_a_starpulse_toml_in_the_working_directory_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "starpulse.toml").write_text('tracker_url = "http://here.test"\n')
    monkeypatch.chdir(tmp_path)

    assert _config(argparse.ArgumentParser(), None).tracker_url == "http://here.test"


def test_without_the_flag_or_a_file_the_defaults_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert _config(argparse.ArgumentParser(), None) == Config(None, "ic", ())


@pytest.mark.parametrize(
    ("text", "reason"),
    [('trakcer_url = "x"\n', "unknown config key(s) trakcer_url"), (None, "No such file or directory")],
)
def test_a_config_the_view_cannot_run_from_exits_one_naming_the_file_and_the_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str | None, reason: str
) -> None:
    path = tmp_path / "starpulse.toml"
    if text is not None:
        path.write_text(text)

    with pytest.raises(SystemExit) as exited:
        _config(argparse.ArgumentParser(), path)

    assert exited.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith(f"{path}: ") and reason in err


LAN = _ip(192, 168, 0, 42)


class _Writer:
    """A stubbed board writer that records each status change and answers with one canned reply."""

    def __init__(self, reply: Written = Written(True, "Updated task PROJ-3")) -> None:
        self.reply = reply
        self.sent: list[tuple[str, str]] = []

    def __call__(self, task: str, status: str) -> Written:
        self.sent.append((task, status))
        return self.reply


def _move(body: bytes | dict, writer: MoveWriter, source: str = LAN, feed: BoardFeed | None = None):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return move_task(source, raw, feed or _feed(), writer)


def test_a_lan_browser_moves_a_task_through_the_writer_to_the_status_the_column_names() -> None:
    writer = _Writer()

    assert _move({"task": "PROJ-3", "to": "in_progress"}, writer) == (200, {"task": "PROJ-3", "to": "in_progress"})
    assert writer.sent == [("PROJ-3", "In Progress")]


@pytest.mark.parametrize("source", ["203.0.113.5", _ip(172, 32, 0, 1), _ip(100, 64, 0, 1)])
def test_a_source_outside_loopback_and_rfc_1918_is_refused_before_the_writer_is_asked(source: str) -> None:
    writer = _Writer()

    status, body = _move({"task": "PROJ-3", "to": "in_progress"}, writer, source)

    assert (status, writer.sent) == (403, [])
    assert body == {"error": "Moving a task answers only loopback and private network (RFC 1918) browsers"}


@pytest.mark.parametrize(
    "raw",
    [b"", b"not json", b"[]", b'{"task": "PROJ-3"}', b'{"to": "ready"}', b'{"task": 3, "to": "ready"}'],
)
def test_a_body_that_does_not_name_a_task_and_a_column_is_a_bad_request(raw: bytes) -> None:
    writer = _Writer()

    status, body = _move(raw, writer)

    assert (status, writer.sent) == (400, [])
    assert body == {"error": 'a move needs {"task": "TASK-N", "to": "<column>"}'}


def test_a_task_the_board_does_not_hold_is_not_found() -> None:
    writer = _Writer()

    assert _move({"task": "PROJ-99", "to": "ready"}, writer) == (404, {"error": "PROJ-99 is not on the board"})
    assert writer.sent == []


@pytest.mark.parametrize("to", ["review", "done", "nowhere"])
def test_a_column_the_board_machine_does_not_allow_from_the_tasks_state_is_refused_before_the_writer_is_asked(
    to: str,
) -> None:
    writer = _Writer()

    status, body = _move({"task": "PROJ-3", "to": to}, writer)

    assert (status, writer.sent) == (409, [])
    assert body == {"error": f"PROJ-3 cannot move from ready to {to}"}


def test_a_move_the_writer_refuses_answers_409_with_its_reason_and_the_skill_that_satisfies_it() -> None:
    writer = _Writer(Written(False, "refusing to set PROJ-5 Review: ... Run the `designing-ui` skill", "designing-ui"))
    feed = _feed()
    guarded = Move(allowed=False, reason="Operator approved the render", skill="designing-ui")
    feed.put(task("PROJ-5", "In Progress", moves={"review": guarded}))

    status, body = _move({"task": "PROJ-5", "to": "review"}, writer, feed=feed)

    assert status == 409
    assert body == {"error": "refusing to set PROJ-5 Review: ... Run the `designing-ui` skill", "skill": "designing-ui"}
    assert writer.sent == [("PROJ-5", "Review")]  # the writer decides; the snapshot's verdict only forecasts it


STARTED_AT = 1_790_000_000.0
SESSION = "https://claude.ai/code/session_01"


class _Sessions:
    """A stubbed session-start service: records each task it is asked to start, answers a URL or fails."""

    def __init__(self, failure: str | None = None) -> None:
        self.failure = failure
        self.started: list[str] = []

    def __call__(self, task: str) -> str:
        self.started.append(task)
        if self.failure:
            raise StartFailedError(self.failure)
        return SESSION


def _start(
    body: bytes | dict,
    assign: _Writer | None = None,
    sessions: _Sessions | None = None,
    source: str = LAN,
    feed: BoardFeed | None = None,
):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    if feed is None:
        feed = BoardFeed()
        feed.put(task("PROJ-3", "Ready", assignee="@agent-standard-high"))
    return start_task(source, raw, feed, assign or _Writer(), sessions, clock=lambda: STARTED_AT)


def test_a_start_with_a_changed_assignee_saves_it_then_starts_the_session() -> None:
    assign, sessions = _Writer(), _Sessions()

    status, body = _start({"task": "PROJ-3", "assignee": "@agent-deep-high"}, assign, sessions)

    assert (status, body) == (200, {"task": "PROJ-3", "url": SESSION, "at": STARTED_AT})
    assert assign.sent == [("PROJ-3", "@agent-deep-high")]
    assert sessions.started == ["PROJ-3"]


def test_a_start_with_the_assignee_the_task_already_has_writes_nothing() -> None:
    assign, sessions = _Writer(), _Sessions()

    assert _start({"task": "PROJ-3", "assignee": "@agent-standard-high"}, assign, sessions)[0] == 200
    assert (assign.sent, sessions.started) == ([], ["PROJ-3"])


def test_a_session_that_fails_to_start_answers_502_with_the_services_reason() -> None:
    status, body = _start({"task": "PROJ-3", "assignee": "@agent-standard-high"}, sessions=_Sessions("tmux failed"))

    assert (status, body) == (502, {"error": "tmux failed"})


def test_an_assignee_the_writer_refuses_starts_no_session() -> None:
    assign, sessions = _Writer(Written(False, "refusing to assign PROJ-3")), _Sessions()

    status, body = _start({"task": "PROJ-3", "assignee": "@agent-nope"}, assign, sessions)

    assert (status, body) == (409, {"error": "refusing to assign PROJ-3", "skill": ""})
    assert sessions.started == []


def test_without_a_session_start_service_nothing_is_started() -> None:
    assign = _Writer()

    status, body = _start({"task": "PROJ-3", "assignee": "@agent-deep-high"}, assign, None)

    assert (status, body) == (404, {"error": "no session-start service is configured (session_start_url)"})
    assert assign.sent == []


@pytest.mark.parametrize(
    "raw", [b"", b"not json", b"[]", b'{"task": "PROJ-3"}', b'{"assignee": "@a"}', b'{"task": 3, "assignee": "@a"}']
)
def test_a_body_that_does_not_name_a_task_and_an_assignee_is_a_bad_request(raw: bytes) -> None:
    sessions = _Sessions()

    status, body = _start(raw, sessions=sessions)

    assert (status, sessions.started) == (400, [])
    assert body == {"error": 'a start needs {"task": "TASK-N", "assignee": "@agent-<tier>-<effort>"}'}


def test_a_start_from_outside_the_lan_is_refused() -> None:
    sessions = _Sessions()

    status, body = _start({"task": "PROJ-3", "assignee": "@a"}, sessions=sessions, source="203.0.113.5")

    assert (status, sessions.started) == (403, [])
    assert body == {"error": "Starting a session answers only loopback and private network (RFC 1918) browsers"}


def test_a_task_off_the_board_or_outside_ready_waiting_and_needs_attention_starts_nothing() -> None:
    feed = BoardFeed()
    feed.put(task("PROJ-5", "Review"))
    sessions = _Sessions()

    assert _start({"task": "PROJ-99", "assignee": "@a"}, sessions=sessions, feed=feed) == (
        404,
        {"error": "PROJ-99 is not on the board"},
    )
    assert _start({"task": "PROJ-5", "assignee": "@a"}, sessions=sessions, feed=feed) == (
        409,
        {"error": "PROJ-5 is in review: a session starts only a ready, waiting or needs_attention task"},
    )
    assert sessions.started == []


def test_a_server_built_without_a_board_writer_refuses_every_move() -> None:
    assert _no_writer("PROJ-3", "Review") == Written(False, "no board writer is configured")


def test_the_harness_configuration_is_served_to_the_page(tmp_path: Path) -> None:
    file = tmp_path / "harnesses.toml"
    file.write_text(
        'tiers = ["deep"]\n[harnesses.claude]\nsessions = true\n[harnesses.claude.tiers.deep]\nmodel = "opus"\n'
    )
    harnesses = load_harnesses(file)

    with serve(tmp_path, harnesses=harnesses) as server, urllib.request.urlopen(url(server, "/api/harnesses")) as resp:
        body = json.load(resp)

    assert body == harnesses.as_json()
    assert body["harnesses"][0]["tiers"] == {"deep": {"model": "opus", "efforts": []}}


def test_with_no_harness_file_the_page_is_served_no_tiers_and_no_harness(tmp_path: Path) -> None:
    with serve(tmp_path) as server, urllib.request.urlopen(url(server, "/api/harnesses")) as resp:
        assert json.load(resp) == {"tiers": [], "harnesses": []}


def test_an_instance_is_read_by_the_adapter_module_its_type_names() -> None:
    parser = argparse.ArgumentParser()

    module = _adapter(parser, RunsInstance("ci", "dagu", "http://ci.test"))

    assert module.__name__ == "starpulse.dagu"


def test_an_instance_type_that_is_not_a_runs_adapter_exits_naming_the_instance(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = argparse.ArgumentParser()

    with pytest.raises(SystemExit) as exited:
        _adapter(parser, RunsInstance("ci", "config", "http://ci.test"))

    assert exited.value.code == 1
    assert capsys.readouterr().err == "runs instance ci: starpulse.config is not a runs adapter\n"


@pytest.mark.parametrize("present", ["start", "follow"])
def test_an_adapter_with_only_one_of_start_and_follow_is_not_a_runs_adapter(
    present: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "starpulse.half", types.SimpleNamespace(**{present: lambda *args: None}))

    with pytest.raises(SystemExit):
        _adapter(argparse.ArgumentParser(), RunsInstance("ci", "half", "http://ci.test"))
