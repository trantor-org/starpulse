"""`serve` starts neither the sampler nor the loop and answers `/api/scheduler` from the worker."""

from pathlib import Path

import pytest

from starpulse.runtime import server
from starpulse.runtime import worker as api_child
from starpulse.scheduler.adapters.remote import Remote
from starpulse.scheduler.bin import scheduler_service as service
from starpulse.tests import fake_board
from starpulse.views.bin import api_worker

BOARD = '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'


def _serve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[list[object], dict[str, object]]:
    monkeypatch.setattr(fake_board, "BUILT", [])
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    monkeypatch.setattr(server, "_STATIC", static)
    monkeypatch.setattr("starpulse.runtime.server.serve_until_stopped", lambda httpd, feed: None)
    started: list[object] = []
    monkeypatch.setattr(service, "start_scheduler", lambda *args, **kwargs: started.append(args) or None)
    handled: dict[str, object] = {}
    monkeypatch.setattr(api_worker, "page_app", lambda *args, **kwargs: handled.update(kwargs, services=args[5]))
    config = tmp_path / "starpulse.toml"
    config.write_text(BOARD)

    api_child.main(["api", "--config", str(config), "--port", "0"])

    return started, handled


def test_serve_starts_neither_the_sampler_nor_the_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started, handled = _serve(tmp_path, monkeypatch)

    assert started == []
    assert isinstance(handled["services"].scheduler, Remote)
