"""`serve` signs its GitHub reads, and every worker it starts, with the token `github_token_env` names."""

import os
from pathlib import Path

from starpulse.runtime import server, supervisor
from starpulse.runtime.config import Config, load


def _config(tmp_path: Path, text: str) -> Config:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return load(path)


def test_serve_exports_the_named_github_token_as_github_token(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, 'github_token_env = "PAT_FOR_TEST"\n')
    monkeypatch.setenv("GITHUB_TOKEN", "previous")
    monkeypatch.setenv("PAT_FOR_TEST", "ghp_value")
    server.export_github_token(config)
    assert os.environ["GITHUB_TOKEN"] == "ghp_value"


def test_serve_leaves_github_token_alone_when_the_named_variable_is_unset(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, 'github_token_env = "PAT_FOR_TEST"\n')
    monkeypatch.setenv("GITHUB_TOKEN", "previous")
    monkeypatch.delenv("PAT_FOR_TEST", raising=False)
    server.export_github_token(config)
    assert os.environ["GITHUB_TOKEN"] == "previous"


def test_serve_overrides_a_literal_gh_token_alias_with_the_named_token(tmp_path: Path, monkeypatch) -> None:
    """systemd's `EnvironmentFile=` leaves `GH_TOKEN="$GITHUB_PERSONAL_ACCESS_TOKEN"` unexpanded, and `gh` reads
    `GH_TOKEN` before `GITHUB_TOKEN`."""
    config = _config(tmp_path, 'github_token_env = "PAT_FOR_TEST"\n')
    monkeypatch.setenv("GH_TOKEN", "$PAT_FOR_TEST")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("PAT_FOR_TEST", "ghp_value")
    server.export_github_token(config)
    assert (os.environ["GH_TOKEN"], os.environ["GITHUB_TOKEN"]) == ("ghp_value", "ghp_value")


def test_serve_leaves_gh_token_alone_when_the_named_variable_is_unset(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, 'github_token_env = "PAT_FOR_TEST"\n')
    monkeypatch.setenv("GH_TOKEN", "previous")
    monkeypatch.delenv("PAT_FOR_TEST", raising=False)
    server.export_github_token(config)
    assert os.environ["GH_TOKEN"] == "previous"


def test_a_supervised_child_is_spawned_with_gh_token_equal_to_the_named_token(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, 'github_token_env = "PAT_FOR_TEST"\n')
    monkeypatch.setenv("GH_TOKEN", "$PAT_FOR_TEST")
    monkeypatch.setenv("PAT_FOR_TEST", "ghp_value")
    spawned: dict[str, dict[str, str]] = {}
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda command, **kwargs: spawned.update(env=kwargs["env"]))
    server.export_github_token(config)
    supervisor.spawn_child(["starpulse", "worker"])
    assert spawned["env"]["GH_TOKEN"] == "ghp_value"
