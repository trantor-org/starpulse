"""`starpulse machine validate|machine import mermaid|config check|demo`: the verbs that need no running server."""

import io
import json
import socket
import urllib.error
import urllib.request
from collections.abc import Sequence
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from starpulse.cli import agent_cli as cli
from starpulse.cli import agent_wire
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.store import EventStore, NewEvent

VALID = Path(__file__).parents[3] / "starpulse" / "machines" / "harness.yaml"


def _run(capsys: pytest.CaptureFixture[str], argv: Sequence[str]) -> tuple[int, Any]:
    """The exit code and the one JSON document on stdout; a second document, or any stderr, fails the test."""
    code = cli.main(argv, {})
    out = capsys.readouterr()
    assert out.err == ""
    return code, json.loads(out.out)


class TestMachineValidate:
    def test_a_schema_error_names_its_file_and_line_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        machine = tmp_path / "flow.yaml"
        machine.write_text(
            "name: flow\nstates:\n  idle: {initial: true}\n  done: {final: maybe}\nevents:\n  GO:\n    - {from: idle, to: done}\n"
        )

        code, document = _run(capsys, ["machine", "validate", str(machine)])

        assert code == 1
        assert document["ok"] is False
        (checked,) = document["machines"]
        assert checked["path"] == str(machine)
        (error,) = checked["errors"]
        assert (error["file"], error["line"]) == (str(machine), 4)
        assert "states/done/final" in error["message"]

    def test_a_migrations_entry_no_live_task_holds_is_refused_naming_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        events = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
        store = EventStore(events.engine)
        store.append(
            "task", "TASK-1", 0, [NewEvent("TaskCreated", {"title": "t", "state": "doing"}, "adin", "operator")]
        )
        Projector(events.engine, store).catch_up()
        (tmp_path / "starpulse.toml").write_text(f'database_url = "sqlite:///{tmp_path / "events.sqlite"}"\n')
        machine = tmp_path / "board.yaml"
        machine.write_text(
            "name: board\nstates:\n  ready: {initial: true}\n  doing: {}\n  done: {final: true}\n"
            "events:\n  go:\n    - {from: ready, to: doing}\n  finish:\n    - {from: doing, to: done}\n"
            "migrations: {doing: doing, blocked: ready}\n"
        )

        code, document = _run(
            capsys, ["machine", "validate", "--config", str(tmp_path / "starpulse.toml"), str(machine)]
        )

        assert code == 1
        (error,) = document["machines"][0]["errors"]
        assert "blocked" in error["message"] and "doing" not in error["message"]

    def test_a_valid_machine_exits_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, document = _run(capsys, ["machine", "validate", str(VALID)])

        assert code == 0
        assert document == {"ok": True, "machines": [{"path": str(VALID), "ok": True, "errors": []}]}

    def test_a_guard_the_adapter_registers_is_not_a_validation_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        machine = tmp_path / "flow.yaml"
        machine.write_text(
            "name: flow\nstates:\n  idle: {initial: true}\n  done: {final: true}\n"
            "events:\n  GO:\n    - {from: idle, to: done, if: ready, action: notify}\n"
        )

        code, document = _run(capsys, ["machine", "validate", str(machine)])

        assert (code, document["ok"]) == (0, True)

    def test_a_compile_error_names_its_file_and_each_path_is_judged_alone(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        broken = tmp_path / "broken.yaml"
        broken.write_text(
            "name: flow\nstates:\n  idle: {initial: true}\nevents:\n  GO:\n    - {from: idle, to: gone}\n"
        )

        code, document = _run(capsys, ["machine", "validate", str(VALID), str(broken)])

        assert code == 1
        assert [(m["path"], m["ok"]) for m in document["machines"]] == [(str(VALID), True), (str(broken), False)]
        (error,) = document["machines"][1]["errors"]
        assert error["file"] == str(broken)
        assert "undeclared state 'gone'" in error["message"]

    def test_a_yaml_syntax_error_names_its_line(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        machine = tmp_path / "flow.yaml"
        machine.write_text("name: flow\nstates: [unclosed\n")

        code, document = _run(capsys, ["machine", "validate", str(machine)])

        assert code == 1
        (error,) = document["machines"][0]["errors"]
        assert (error["file"], error["line"]) == (str(machine), 3)

    def test_a_missing_file_is_a_refusal_naming_it(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code, document = _run(capsys, ["machine", "validate", str(tmp_path / "nope.yaml")])

        assert code == 1
        assert document["machines"][0]["errors"][0]["file"] == str(tmp_path / "nope.yaml")


class TestConfigCheck:
    def test_an_unknown_key_is_named_and_exits_1(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        file = tmp_path / "starpulse.toml"
        file.write_text('colour = "red"\n')

        code, document = _run(capsys, ["config", "check", "--config", str(file)])

        assert code == 1
        assert document["ok"] is False
        assert document["unknown_keys"] == ["colour"]
        assert "colour" in document["errors"][0]
        assert document["config"] is None

    def test_a_producers_table_is_validated_and_shown(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        file = tmp_path / "starpulse.toml"
        file.write_text(
            '[[producers]]\nname = "ci"\ntoken_env = "CI_TOKEN"\nmachines = ["delivery"]\nactors = ["ci"]\n'
        )

        code, document = _run(capsys, ["config", "check", "--config", str(file)])

        assert code == 0
        assert document["config"]["producers"] == [
            {"name": "ci", "token_env": "CI_TOKEN", "machines": ["delivery"], "actors": ["ci"]}
        ]

    def test_a_producers_table_missing_its_token_env_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        file = tmp_path / "starpulse.toml"
        file.write_text('[[producers]]\nname = "ci"\nmachines = ["delivery"]\nactors = ["ci"]\n')

        code, document = _run(capsys, ["config", "check", "--config", str(file)])

        assert (code, document["ok"], "token_env" in document["errors"][0]) == (1, False, True)

    @pytest.mark.parametrize(("actor", "errors"), [("prod/ghost", ["prod/ghost"]), ("prod/nightly", [])])
    def test_a_machine_writer_no_adapter_lists_is_refused_as_serve_refuses_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], actor: str, errors: list[str]
    ) -> None:
        file = tmp_path / "starpulse.toml"
        file.write_text(
            '[board]\ntype = "machines"\n\n[[runs]]\nname = "prod"\ntype = "dagu"\nurl = "http://prod.example.test:8085"\n'
            '[runs.domains]\nOps = ["nightly"]\n'
        )
        machines = tmp_path / ".starpulse" / "machines"
        machines.mkdir(parents=True)
        (machines / "flow.yaml").write_text(
            "name: flow\nstates:\n  idle: {initial: true}\n  done: {final: true}\n"
            f"events:\n  GO:\n    - {{from: idle, to: done}}\nwriters:\n  GO: [{{actor: {actor}, trigger: emit}}]\n"
        )

        code, document = _run(capsys, ["config", "check", "--config", str(file)])

        assert (code, document["ok"]) == (1 if errors else 0, not errors)
        assert [name for name in errors if name in " ".join(document["errors"])] == errors
        assert len(document["errors"]) == len(errors)

    def test_the_effective_config_shows_every_default(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        file = tmp_path / "starpulse.toml"
        file.write_text('tracker_url = "http://tracker.example"\n')

        code, document = _run(capsys, ["config", "check", "--config", str(file)])

        assert code == 0
        assert document["file"] == str(file)
        assert document["unknown_keys"] == [] and document["errors"] == []
        assert document["config"] == {
            "tracker_url": "http://tracker.example",
            "mode": "ic",
            "runs": [],
            "repos": [],
            "harnesses": None,
            "board_type": "native",
            "board": {},
            "database_url": None,
            "session_start_url": None,
            "level": None,
            "producers": [],
            "refresh_token_env": None,
            "take_over_command": None,
            "pull_requests": True,
            "runs_worker": False,
            "flow_metrics_worker": False,
            "search_worker": False,
            "board_worker": False,
            "api_worker": False,
            "tls": None,
            "slow_read_seconds": 1.0,
            "worker_memory": {
                "pulls": {"soft_mb": 768, "hard_mb": 1536},
                "scheduler": {"soft_mb": 384, "hard_mb": 768},
                "runs": {"soft_mb": 512, "hard_mb": 1024},
                "flow-metrics": {"soft_mb": 384, "hard_mb": 768},
                "search": {"soft_mb": 384, "hard_mb": 768},
                "board": {"soft_mb": 768, "hard_mb": 1536},
            },
            "event_log_retention_days": 7,
            "event_log_archive_dir": "starpulse-archive",
            "ci": [],
            "scheduler": {
                "lane": None,
                "review_lane": None,
                "unsized_points": 3,
                "idle_minutes": 30,
                "state_dir": None,
                "tier_weights": {"fast": 1, "standard": 2, "deep": 4},
                "priority_matrix": {
                    "low/low": 1.0,
                    "low/medium": 2.0,
                    "low/high": 3.0,
                    "medium/low": 2.0,
                    "medium/medium": 4.0,
                    "medium/high": 6.0,
                    "high/low": 3.0,
                    "high/medium": 6.0,
                    "high/high": 9.0,
                    "default": 4.0,
                },
                "limits": {"cpu": 80, "memory": 80, "sessions": 2, "review": 20},
                "session_limits": {},
            },
            "release": None,
            "analytics": {
                "roots": [],
                "stop_activities": [],
                "lifecycle_skills": [],
                "skill_loads": [],
                "injected_openings": [],
                "operator_tools": [],
                "claims": [],
                "completion_skill": "",
                "completion_call": None,
                "skill_machines": [],
                "labeller": None,
                "eval_attribute": "",
                "ladder": [],
                "weights": [],
                "default_repo": "",
            },
            "task_actor": False,
            "search": {"embeddings_url": None, "model": None, "token_env": None},
            "project": {"commands": {}},
            "cursor_context": {"limit_tokens": 150000, "window_tokens": 200000, "wrapup_s": 600.0},
        }

    def test_a_declared_analytics_table_shows_as_lists_and_pattern_text(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        file = tmp_path / "starpulse.toml"
        file.write_text(
            "[analytics]\n"
            'roots = ["/r"]\n'
            'stop_activities = ["Bash", "Read"]\n'
            'lifecycle_skills = ["starting-tasks"]\n'
            'injected_openings = ["<task-notification"]\n'
            'operator_tools = ["ExitPlanMode", "AskUserQuestion"]\n'
            "claims = ['start\\s+(TASK-\\d+)']\n"
            'completion_skill = "completing-tasks"\n'
            "completion_call = 'deliver\\b'\n"
            'eval_attribute = "x.eval"\n'
            'ladder = ["haiku-low", "haiku-high"]\n'
            'default_repo = "o/r"\n'
            "[analytics.weights]\n"
            "clean = 50\n"
            "[[analytics.skill_loads]]\n"
            'skill = "verifying-claims"\n'
            'title = "^verify"\n'
            'label = "validation"\n'
            "[[analytics.skill_machines]]\n"
            'skill = "developing-test-first"\n'
            'stages = [{ name = "RED", activities = ["pytest"], ok = false }]\n'
            "[analytics.labeller]\n"
            'url = "http://labeller/v1"\n'
            'model = "intent"\n'
            "[analytics.labeller.criteria]\n"
            'approval = "Proceed."\n'
        )

        code, document = _run(capsys, ["config", "check", "--config", str(file)])

        assert code == 0
        assert document["config"]["analytics"] == {
            "roots": ["/r"],
            "stop_activities": ["Bash", "Read"],
            "lifecycle_skills": ["starting-tasks"],
            "skill_loads": [{"skill": "verifying-claims", "activities": [], "title": "^verify", "label": "validation"}],
            "injected_openings": ["<task-notification"],
            "operator_tools": ["AskUserQuestion", "ExitPlanMode"],
            "claims": [r"start\s+(TASK-\d+)"],
            "completion_skill": "completing-tasks",
            "completion_call": r"deliver\b",
            "skill_machines": [
                {
                    "skill": "developing-test-first",
                    "stages": [{"name": "RED", "activities": ["pytest"], "ok": False}],
                }
            ],
            "eval_attribute": "x.eval",
            "ladder": ["haiku-low", "haiku-high"],
            "weights": [["clean", 50.0]],
            "default_repo": "o/r",
            "labeller": {
                "url": "http://labeller/v1",
                "model": "intent",
                "criteria": {"approval": "Proceed."},
                "instructions": "",
                "timeout": 2.0,
            },
        }

    def test_with_no_file_it_reports_the_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)

        code, document = _run(capsys, ["config", "check"])

        assert (code, document["ok"], document["file"]) == (0, True, None)
        assert document["config"]["mode"] == "ic"

    def test_a_nested_problem_is_an_error_not_an_unknown_key(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        file = tmp_path / "starpulse.toml"
        file.write_text('mode = "team"\n')

        code, document = _run(capsys, ["config", "check", "--config", str(file)])

        assert code == 1
        assert document["unknown_keys"] == []
        assert "team" in document["errors"][0]


DIAGRAM = "stateDiagram-v2\n    [*] --> open\n    open --> closed : Close it\n    closed --> [*]\n"


class TestMachineImportMermaid:
    def test_the_draft_is_written_and_validates(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        source, out = tmp_path / "flow.mmd", tmp_path / "flow.yaml"
        source.write_text(DIAGRAM)

        code, document = _run(capsys, ["machine", "import", "mermaid", str(source), "--out", str(out)])

        assert (code, document) == (0, {"written": str(out)})
        code, validated = _run(capsys, ["machine", "validate", str(out)])
        assert (code, validated["ok"]) == (0, True)

    def test_a_missing_source_is_not_found(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code, document = _run(capsys, ["machine", "import", "mermaid", str(tmp_path / "nope.mmd")])

        assert (code, document["code"]) == (4, "not_found")

    def test_an_existing_definition_is_never_overwritten(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        source, out = tmp_path / "flow.mmd", tmp_path / "flow.yaml"
        source.write_text(DIAGRAM)
        out.write_text("authored: true\n")

        code, document = _run(capsys, ["machine", "import", "mermaid", str(source), "--out", str(out)])

        assert (code, document["code"]) == (1, "refused")
        assert out.read_text() == "authored: true\n"

    def test_a_diagram_it_cannot_draft_is_refused(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        source = tmp_path / "flow.mmd"
        source.write_text("flowchart TD\n    a --> b\n")

        code, document = _run(capsys, ["machine", "import", "mermaid", str(source), "--out", str(tmp_path / "x.yaml")])

        assert (code, document["code"]) == (1, "refused")
        assert "stateDiagram-v2" in document["error"]


class TestDemo:
    def _design(self, root: Path) -> Path:
        root.mkdir()
        board = {"agents": [{"id": "PROJ-1", "title": "Rotate the secret", "state": "ready"}]}
        snap = {"now": 1.0, "dags": [], "flows": {"board": board, "in-progress": {"agents": []}}}
        (root / "data.js").write_text("window.SNAP = " + json.dumps(snap) + ";\n")
        (root / "index.html").write_text('<body><script src="data.js"></script></body>')
        return root

    def test_the_page_is_built_from_a_mockup_with_every_task_scrubbed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "demo.html"

        code, document = _run(capsys, ["demo", "--mockup", str(self._design(tmp_path / "design")), "--out", str(out)])

        assert (code, document) == (0, {"written": str(out)})
        page = out.read_text()
        assert "DEMO-1" in page and "PROJ-1" not in page and "secret" not in page

    def test_a_server_that_is_down_is_unavailable(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            down = f"http://127.0.0.1:{sock.getsockname()[1]}"

        code, document = _run(capsys, ["demo", "--server", down, "--out", str(tmp_path / "demo.html")])

        assert (code, document["code"]) == (3, "unavailable")
        assert not (tmp_path / "demo.html").exists()


class TestSearchTimeout:
    def test_a_search_that_times_out_names_a_slow_search_not_an_unreachable_server(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def urlopen(request, timeout=None):
            raise TimeoutError("timed out")

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)

        code, document = _run(capsys, ["search", "--server", "http://127.0.0.1:9", "--", "drain"])

        assert code == 3
        assert document["code"] == "unavailable"
        assert "slow search" in document["error"]
        assert "cannot reach StarPulse" not in document["error"]


class TestRestartingServer:
    def _answering(self, monkeypatch: pytest.MonkeyPatch, headers: Message) -> None:
        def urlopen(request, timeout=None):
            body = io.BytesIO(b'{"error": "PROJ-3 is not on the board yet: the board is replaying its feed, retry"}')
            raise urllib.error.HTTPError(request.full_url, 503, "Service Unavailable", headers, body)

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    def test_a_503_with_retry_after_is_an_unavailable_error_naming_the_seconds_to_wait(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        headers = Message()
        headers["Retry-After"] = "3"
        self._answering(monkeypatch, headers)

        code, document = _run(capsys, ["task", "restore", "PROJ-3", "--server", "http://127.0.0.1:9"])

        assert (code, document["code"], document["retry_after"]) == (3, "unavailable", 3)
        assert "replaying its feed" in document["error"]

    def test_a_503_without_retry_after_names_no_wait(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._answering(monkeypatch, Message())

        code, document = _run(capsys, ["task", "restore", "PROJ-3", "--server", "http://127.0.0.1:9"])

        assert code == 3
        assert "retry_after" not in document


class TestMachineShow:
    FLOW = {
        "name": "in-progress",
        "agents": [{"id": "PROJ-1", "state": "start"}],
        "machine": {
            "states": [
                {"id": "start", "name": "Start", "initial": True, "final": False},
                {"id": "done", "name": "Done", "initial": False, "final": True},
            ],
            "transitions": [{"source": "start", "target": "done", "event": "FINISH"}],
            "writers": {"FINISH": [{"actor": "ops/nightly", "trigger": "emit"}]},
            "submachines": [{"state": "start", "machine": "review", "exits": {}, "parent": "in-progress", "when": ""}],
            "launches": {"ops/nightly": {"skill": "audit", "machine": "review"}},
        },
    }

    @pytest.fixture(autouse=True)
    def served(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(agent_wire, "get_snapshot", lambda url: {"flows": [self.FLOW]})

    def test_it_returns_the_submachines_launches_and_writers_the_machine_declares(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, document = _run(capsys, ["machine", "show", "in-progress"])

        assert code == 0
        machine = self.FLOW["machine"]
        assert {key: document[key] for key in ("submachines", "launches", "writers")} == {
            key: machine[key] for key in ("submachines", "launches", "writers")
        }

    def test_a_machine_that_declares_none_of_them_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bare = {**self.FLOW, "machine": {key: self.FLOW["machine"][key] for key in ("states", "transitions")}}
        monkeypatch.setattr(agent_wire, "get_snapshot", lambda url: {"flows": [bare]})

        _, document = _run(capsys, ["machine", "show", "in-progress"])

        assert not {"submachines", "launches", "writers"} & document.keys()

    def test_format_dot_returns_the_static_diagram_beside_the_machine(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, document = _run(capsys, ["machine", "show", "in-progress", "--format", "dot"])

        assert code == 0
        assert document["format"] == "dot"
        assert document["diagram"].startswith('digraph "in-progress" {')
        assert '"start" -> "done" [label="FINISH"' in document["diagram"]

    def test_the_default_format_is_json_and_draws_no_diagram(self, capsys: pytest.CaptureFixture[str]) -> None:
        _, document = _run(capsys, ["machine", "show", "in-progress"])

        assert "diagram" not in document
