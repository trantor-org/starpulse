"""`starpulse command show`: what a project's step needs before the agent writes its files."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from starpulse.cli import agent_cli as cli

DELIVER = '[project.commands]\ndeliver = ["./deliver", "--worktree", "{worktree}", "--message-file", "{message}", "--body-file", "{body}"]\n'
SKILL = Path(__file__).parents[3] / "starpulse" / "skills" / "deliver" / "SKILL.md"
REVIEWER = "# Title\n\n## Summary\n\n## For the reviewer\n\n## Verification\n"
OTHER = "## Why\n\n## Risk\n"


def _show(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, name: str, toml: str = DELIVER, **files: str
) -> tuple[int, Any]:
    for relative, text in files.items():
        target = tmp_path / relative.replace("__", "/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    config = tmp_path / "starpulse.toml"
    config.write_text(toml)
    code = cli.main(["command", "show", name, "--config", str(config)], {})
    return code, json.loads(capsys.readouterr().out)


def test_the_message_and_body_placeholders_are_named_before_any_file_is_written(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, document = _show(capsys, tmp_path, "deliver")

    assert code == 0
    assert document["args"] == ["message", "body"]
    assert "--arg message=<message> --arg body=<body>" in document["invocation"]


def test_the_projects_pr_body_template_is_printed_with_its_path(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _, document = _show(capsys, tmp_path, "deliver", **{".github__pull_request_template.md": REVIEWER})

    assert document["pr_body_template"] == {"path": ".github/pull_request_template.md", "text": REVIEWER}


def test_another_projects_template_is_printed_not_trantors(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    _, document = _show(capsys, tmp_path, "deliver", **{"docs__pull_request_template.md": OTHER})

    assert document["pr_body_template"]["text"] == OTHER
    assert "For the reviewer" not in document["pr_body_template"]["text"]


def test_a_project_with_no_template_reports_none(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    _, document = _show(capsys, tmp_path, "deliver")

    assert document["pr_body_template"] is None


def test_a_step_without_a_body_placeholder_prints_no_template(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    toml = '[project.commands]\ncheck = ["lint", "{args}"]\n'

    _, document = _show(capsys, tmp_path, "check", toml, **{".github__pull_request_template.md": REVIEWER})

    assert (document["args"], document["pr_body_template"]) == ([], None)


def test_an_unmapped_step_exits_4_with_the_fallback(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, document = _show(capsys, tmp_path, "nope")

    assert code == 4
    assert document["fallback"] == "AGENTS.md"


def test_the_deliver_skill_names_the_args_the_configured_argv_needs_and_runs_show_first(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    text = SKILL.read_text()
    launch = re.search(r"command run deliver([^`]*)`", text)
    assert launch
    named = re.findall(r"--arg\s+(\w+)=", launch.group(1))
    _, document = _show(capsys, tmp_path, "deliver")

    assert named == document["args"]
    assert text.index("command show deliver") < text.index("## 4. Deliver")


HEADING_FREE = "**Task:** TASK-11602\n\nAdds the hc t36 collector and its tests; all checks pass locally.\n"
TRANTOR_TEMPLATE = Path(__file__).parents[3] / ".github" / "pull_request_template.md"


def _sections(text: str) -> list[str]:
    return re.findall(r"^## (.+)$", re.sub(r"<!--.*?-->", "", text, flags=re.S), flags=re.M)


def test_the_printed_trantor_template_gives_a_body_its_required_sections_and_a_heading_free_body_lacks_them(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _, document = _show(capsys, tmp_path, "deliver", **{".github__pull_request_template.md": TRANTOR_TEMPLATE.read_text()})
    required = ["Summary", "For the reviewer", "Verification"]

    assert _sections(document["pr_body_template"]["text"]) == required
    assert _sections(HEADING_FREE) == []


def test_a_symlinked_config_finds_the_template_beside_the_link(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / "starpulse.toml").write_text(DELIVER)
    (tmp_path / "starpulse.toml").symlink_to("infra/starpulse.toml")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "pull_request_template.md").write_text(REVIEWER)
    monkeypatch.chdir(tmp_path)

    code = cli.main(["command", "show", "deliver"], {})

    assert code == 0
    assert json.loads(capsys.readouterr().out)["pr_body_template"]["text"] == REVIEWER
