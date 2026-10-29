"""`serve` signs its GitHub reads, and every worker it starts, with the token `github_token_env` names."""

import os
from pathlib import Path

from starpulse.runtime import server
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
