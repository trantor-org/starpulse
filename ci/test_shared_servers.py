"""A shared server is built again only after a request that is not a read."""

from __future__ import annotations

from pathlib import Path

import pytest
import shared_servers
from starpulse._internal.hub.gate_request import GateRequest


def _server(tmp_path: Path):
    """A fixture's builder: a generator yielding the server's URL."""
    yield "http://127.0.0.1:1"


def _host(tmp_path: Path) -> shared_servers._Hosted:
    return shared_servers._Hosted(tmp_path, _server, {})


def _request(host: shared_servers._Hosted, command: str) -> None:
    """One request the gate lets in."""
    assert host.gate(GateRequest(command, "/api/x", {}))


@pytest.mark.parametrize(("command", "wrote"), [("GET", False), ("POST", True), ("PATCH", True)])
def test_only_a_request_that_is_not_a_read_marks_the_server_for_a_rebuild(tmp_path, command, wrote):
    host = _host(tmp_path)

    _request(host, command)

    assert host.wrote is wrote


def test_a_server_that_wrote_is_built_again_on_the_same_port_and_url_in_an_empty_directory(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    host = shared_servers._Hosted(root, _server, {})
    host.start()
    (root / "left-behind").write_text("")
    _request(host, "POST")

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
