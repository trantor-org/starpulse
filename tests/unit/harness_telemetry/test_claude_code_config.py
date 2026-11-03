"""The `[claude_code]` table: whether the Claude Code adapter runs under `serve`, where it listens, and what it refuses."""

import re
from pathlib import Path

import pytest
from starpulse.harness_telemetry.model.claude_code_config import ClaudeCode
from starpulse.runtime.config import ConfigError, load


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return path


def test_no_table_runs_no_adapter(tmp_path: Path) -> None:
    assert load(None).claude_code is None
    assert load(_write(tmp_path, "")).claude_code is None


def test_an_empty_table_runs_the_adapter_on_loopback_4318_with_no_redactor(tmp_path: Path) -> None:
    assert load(_write(tmp_path, "[claude_code]\n")).claude_code == ClaudeCode(
        host="127.0.0.1",
        port=4318,
        key=r"TASK-\d+",
        branch=r"(?i)(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)",
        key_format="TASK-{}",
        redactor=None,
    )


def test_a_table_sets_the_listener_the_task_keys_and_the_redactor(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[claude_code]\nhost = "0.0.0.0"\nport = 4321\nkey = "PROJ-\\\\d+"\nbranch = "proj-(\\\\d+)"\n'
        'key_format = "PROJ-{}"\nredactor = "pkg.mod:redact"\n',
    )

    assert load(path).claude_code == ClaudeCode("0.0.0.0", 4321, r"PROJ-\d+", r"proj-(\d+)", "PROJ-{}", "pkg.mod:redact")


@pytest.mark.parametrize(
    ("table", "refusal"),
    [
        ("port = 0", "claude_code: port must be a whole number from 1 to 65535"),
        ("port = 70000", "claude_code: port must be a whole number from 1 to 65535"),
        ("port = '4321'", "claude_code: port must be a whole number from 1 to 65535"),
        ("host = 1", "claude_code: host must be a non-empty string"),
        ("redactor = ''", "claude_code: redactor must be a non-empty string"),
        ("branch = '('", "claude_code: branch is not a regular expression"),
        ("tcp = 1", "claude_code: unknown key(s) tcp"),
    ],
)
def test_a_table_the_adapter_cannot_run_from_is_refused_naming_the_key(
    tmp_path: Path, table: str, refusal: str
) -> None:
    with pytest.raises(ConfigError, match=re.escape(refusal)):
        load(_write(tmp_path, f"[claude_code]\n{table}\n"))
