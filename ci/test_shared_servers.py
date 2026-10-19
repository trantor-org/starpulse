"""A shared server is built again only after a request the server accepted changed it."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import shared_servers


def _server(tmp_path: Path):
    """A fixture's builder: a generator yielding the server's URL."""
    yield "http://127.0.0.1:1"


def _host(tmp_path: Path) -> shared_servers._Hosted:
    return shared_servers._Hosted(tmp_path, _server, {})


def _request(host: shared_servers._Hosted, command: str, status: int) -> None:
    """One request the gate lets in and the server answers with `status`."""
    handler = SimpleNamespace(command=command, send_response=lambda code, message=None: None)
    assert host.gate(handler)
    handler.send_response(status)


@pytest.mark.parametrize(("command", "status", "wrote"), [("GET", 200, False), ("POST", 200, True), ("POST", 409, False)])
def test_only_a_write_the_server_accepted_marks_the_server_for_a_rebuild(tmp_path, command, status, wrote):
    host = _host(tmp_path)

    _request(host, command, status)

    assert host.wrote is wrote


def test_a_refusal_after_an_accepted_write_leaves_the_server_marked(tmp_path):
    host = _host(tmp_path)

    _request(host, "POST", 200)
    _request(host, "POST", 403)

    assert host.wrote is True


def test_a_server_that_wrote_is_built_again_on_the_same_port_and_url_in_an_empty_directory(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    host = shared_servers._Hosted(root, _server, {})
    host.start()
    (root / "left-behind").write_text("")
    _request(host, "POST", 200)

    host.renew()

    assert host.url == "http://127.0.0.1:1"
    assert list(root.iterdir()) == []
    assert host.wrote is False


def test_a_server_that_only_answered_reads_is_left_as_it_is(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    host = shared_servers._Hosted(root, _server, {})
    host.start()
    (root / "kept").write_text("")

    host.renew()

    assert [path.name for path in root.iterdir()] == ["kept"]
