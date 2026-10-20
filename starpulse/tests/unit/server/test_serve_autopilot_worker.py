"""`serve` starts neither the sampler nor the loop and answers `/api/autopilot` from the worker."""

from pathlib import Path

import pytest

from starpulse._internal.autopilot.remote import Remote
from starpulse._internal.server import autopilot_service as service
from starpulse._internal.server import server
from starpulse._internal.server import worker as api_child
from starpulse.tests import fake_board

BOARD = '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'


def _serve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[list[object], dict[str, object]]:
    monkeypatch.setattr(fake_board, "BUILT", [])
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    monkeypatch.setattr(server, "_STATIC", static)
    monkeypatch.setattr(server, "serve_until_stopped", lambda httpd, feed: None)
    started: list[object] = []
    monkeypatch.setattr(service, "start_autopilot", lambda *args, **kwargs: started.append(args) or None)
    handled: dict[str, object] = {}
    monkeypatch.setattr(server, "request_handler", lambda *args, **kwargs: handled.update(kwargs, services=args[5]))
    config = tmp_path / "starpulse.toml"
    config.write_text(BOARD)

    api_child.main(["api", "--config", str(config), "--port", "0"])

    return started, handled


def test_serve_starts_neither_the_sampler_nor_the_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started, handled = _serve(tmp_path, monkeypatch)

    assert started == []
    assert isinstance(handled["services"].autopilot, Remote)
