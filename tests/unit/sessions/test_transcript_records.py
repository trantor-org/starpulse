import json
import re
from pathlib import Path
from typing import Any

import pytest
from starpulse.cli import agent_cli as cli
from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.sessions.transcript_records import records_by_task, session_records

KEYS = TaskKeys(key=re.compile(r"TASK-\d+"), branch=re.compile(r"(?i)(?:[\w.-]+/)*task-(\d+)"), key_format="TASK-{}")
ANALYTICS = Analytics(claims=(re.compile(r"(?i:agent-cmd\s+start\s+(TASK-\d+))\b"), re.compile(r"^\s*(TASK-\d+)\s*$")))


def _use(name: str, **given: Any) -> dict[str, Any]:
    return {"message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": name, "input": given}]}}


def _text(text: str, branch: str = "main") -> dict[str, Any]:
    return {"gitBranch": branch, "message": {"role": "user", "content": text}}


def _on(branch: str, record: dict[str, Any]) -> dict[str, Any]:
    return {**record, "gitBranch": branch}


def _tasks(found: dict[str | None, list[dict[str, Any]]]) -> dict[str | None, int]:
    return {task: len(records) for task, records in found.items()}


class TestRecordsByTask:
    def test_a_shell_claim_starts_a_task_and_a_second_claim_starts_the_next(self) -> None:
        records = [
            _on("main", _use("Bash", command="uv run agent-cmd start TASK-1 2>&1 | tail")),
            _text("a"),
            _on("main", _use("Bash", command="agent-cmd start task-2")),
            _text("b"),
            _text("c"),
        ]

        assert _tasks(records_by_task(records, KEYS, ANALYTICS)) == {"TASK-1": 2, "TASK-2": 3}

    def test_a_skill_call_whose_args_are_the_key_claims_it(self) -> None:
        records = [_text("x"), _use("Skill", skill="starting-task", args="TASK-7"), _text("y")]

        assert list(records_by_task(records, KEYS, ANALYTICS)) == ["TASK-7"]

    def test_a_branch_naming_a_task_claims_it_from_that_record_on(self) -> None:
        records = [_text("a"), _text("b", "claude/task-9"), _text("c", "claude/task-9")]

        found = records_by_task(records, KEYS, ANALYTICS)

        assert _tasks(found) == {"TASK-9": 3}  # the record before the first naming joins the first task

    def test_a_session_that_names_no_task_is_one_unattributed_group(self) -> None:
        assert _tasks(records_by_task([_text("a"), _text("b")], KEYS, ANALYTICS)) == {None: 2}

    def test_a_claim_inside_a_heredoc_body_claims_nothing(self) -> None:
        command = "cat <<'EOF'\nagent-cmd start TASK-5\nEOF"

        assert list(records_by_task([_use("Bash", command=command)], KEYS, ANALYTICS)) == [None]


class TestSessionRecords:
    def test_a_resumed_copy_adds_only_the_uuids_not_yet_seen(self, tmp_path: Path) -> None:
        for project, uuids, stamp in (("-a", ("u1", "u2"), "2026-01-01"), ("-b", ("u2", "u3"), "2026-01-02")):
            (tmp_path / project).mkdir()
            lines = [json.dumps({"uuid": u, "timestamp": stamp}) for u in uuids]
            (tmp_path / project / "s-1.jsonl").write_text("\n".join(lines) + "\nnot json\n")

        assert [r["uuid"] for r in session_records(tmp_path, "s-1")] == ["u1", "u2", "u3"]

    def test_no_transcript_is_none(self, tmp_path: Path) -> None:
        assert session_records(tmp_path, "s-1") is None

    @pytest.mark.parametrize("session", ["../x", "", "a/b"])
    def test_a_session_id_that_is_a_path_reads_nothing(self, tmp_path: Path, session: str) -> None:
        assert session_records(tmp_path, session) is None


class TestSessionRecordsVerb:
    def test_prints_the_groups_in_first_claim_order(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        transcripts = tmp_path / "projects"
        (transcripts / "-p").mkdir(parents=True)
        records = [_use("Bash", command="agent-cmd start TASK-3"), _text("a", "claude/task-3")]
        (transcripts / "-p" / "s-1.jsonl").write_text("\n".join(json.dumps(r) for r in records))
        config = tmp_path / "starpulse.toml"
        config.write_text('[analytics]\nclaims = ["agent-cmd\\\\s+start\\\\s+(TASK-\\\\d+)"]\n')

        code = cli.main(["session", "records", "s-1", "--config", str(config), "--transcripts", str(transcripts)], {})
        document = json.loads(capsys.readouterr().out)

        assert code == 0
        assert document["session"] == "s-1"
        assert [(g["task"], len(g["records"])) for g in document["groups"]] == [("TASK-3", 2)]

    def test_an_unknown_session_exits_4(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "starpulse.toml").write_text("")
        argv = ["session", "records", "nope", "--transcripts", str(tmp_path), "--config", str(tmp_path / "starpulse.toml")]

        assert cli.main(argv, {}) == 4
        assert json.loads(capsys.readouterr().out)["code"] == "not_found"
