"""`serve` supervises a `starpulse worker` child for each context whose `*_worker` setting is false, and runs no context's threads itself."""

from pathlib import Path

import pytest

from starpulse._internal.autopilot.remote import Remote
from starpulse._internal.server import autopilot_service as service
from starpulse._internal.server import server
from starpulse.tests import fake_board
from starpulse.tests.conftest import FakeSupervisor

BOARD = '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'


def _serve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: str, ending: type[BaseException] | None = None
) -> tuple[dict[str, object], list[str]]:
    monkeypatch.setattr(fake_board, "BUILT", [])
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    monkeypatch.setattr(server, "_STATIC", static)

    def end(httpd: object, feed: object) -> None:
        if ending:
            raise ending

    monkeypatch.setattr(server, "serve_until_stopped", end)
    threads: list[str] = []
    monkeypatch.setattr(service, "start_autopilot", lambda *args, **kwargs: threads.append("autopilot"))
    monkeypatch.setattr(server, "start_delivery", lambda *args, **kwargs: threads.append("delivery") or (None, None))
    handled: dict[str, object] = {}
    monkeypatch.setattr(server, "request_handler", lambda *args, **kwargs: handled.update(kwargs))
    config = tmp_path / "starpulse.toml"
    config.write_text(settings + BOARD)

    try:
        server.main(["--config", str(config), "--port", "0"])
    except SystemExit, KeyboardInterrupt:
        pass

    return handled, threads


def test_serve_supervises_both_workers_and_starts_neither_context_in_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor]
) -> None:
    handled, threads = _serve(tmp_path, monkeypatch, "")

    assert threads == []
    assert isinstance(handled["autopilot"], Remote)
    [supervisor] = supervisors
    assert set(supervisor.commands) == {"pulls", "autopilot"}
    assert supervisor.started


@pytest.mark.parametrize(
    ("settings", "supervised"),
    [
        ("delivery_worker = true\n", {"autopilot"}),
        ("autopilot_worker = true\n", {"pulls"}),
        ("delivery_worker = true\nautopilot_worker = true\n", set()),
    ],
)
def test_a_true_worker_setting_gets_neither_a_thread_nor_a_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    supervisors: list[FakeSupervisor],
    settings: str,
    supervised: set[str],
) -> None:
    _, threads = _serve(tmp_path, monkeypatch, settings)

    assert threads == []
    assert set(supervisors[0].commands) == supervised


@pytest.mark.parametrize("ending", [None, KeyboardInterrupt, SystemExit])
def test_serve_stops_its_children_however_it_ends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    supervisors: list[FakeSupervisor],
    ending: type[BaseException] | None,
) -> None:
    _serve(tmp_path, monkeypatch, "", ending)

    assert supervisors[0].stopped
