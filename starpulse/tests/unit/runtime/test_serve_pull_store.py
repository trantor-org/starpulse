"""`serve` keeps the pull request store unless its config turns it off."""

from pathlib import Path

import pytest

from starpulse._internal.server import server, worker
from starpulse.tests import fake_board


class Sync:
    built: list["Sync"] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        Sync.built.append(self)

    def run_forever(self) -> None:
        pass

    def request(self, repo: str, number: int) -> None:
        pass

    def project(self) -> None:
        pass


@pytest.mark.parametrize(("line", "kept"), [("", True), ("pull_requests = false\n", False)])
def test_serve_starts_the_pull_store_only_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, line: str, kept: bool
) -> None:
    monkeypatch.setattr(fake_board, "BUILT", [])
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    monkeypatch.setattr(server, "_STATIC", static)
    monkeypatch.setattr(worker, "hold", lambda *args: None)
    monkeypatch.setattr(server.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(server, "PullSync", Sync)
    monkeypatch.setattr(Sync, "built", [])
    config = tmp_path / "starpulse.toml"
    config.write_text(line + '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["open", "shut"]\n')

    worker.main(["pulls", "--config", str(config)])

    assert len(Sync.built) == int(kept)
