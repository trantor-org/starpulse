"""`/api/forwarding`: the instance's own page reads what the forwarder sends and flips the opt-in."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from starpulse._internal.api.adapter_kit import serve, url
from starpulse._internal.api.writes import forwarding
from starpulse.tests.unit.test_forwarder import Rig


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def _put(rig: Rig, body: object, source: str = "127.0.0.1") -> tuple[int, dict]:
    return forwarding(source, "PUT", json.dumps(body).encode(), rig.forwarder())


def test_a_get_answers_the_forwarders_status_marked_configured(rig: Rig) -> None:
    rig.move("T-1", actor="ana")
    forwarder = rig.forwarder()

    status, body = forwarding("127.0.0.1", "GET", b"", forwarder)

    assert status == 200
    assert body == {"configured": True, **forwarder.status()}
    assert body["names"] is False


def test_an_instance_without_a_forward_block_answers_not_configured(rig: Rig) -> None:
    assert forwarding("127.0.0.1", "GET", b"", None) == (200, {"configured": False})


def test_a_put_cannot_opt_in_an_instance_that_forwards_nothing(rig: Rig) -> None:
    status, body = forwarding("127.0.0.1", "PUT", b'{"opt_in": true}', None)

    assert status == 404 and "forward" in body["error"]
    assert rig.opt_in.get() is False


def test_a_put_opts_in_and_out_through_the_file_the_forwarder_reads(rig: Rig) -> None:
    rig.move("T-1", actor="ana")

    assert _put(rig, {"opt_in": True})[1]["names"] is True
    assert rig.opt_in.get() is True
    rig.forwarder().step()
    assert rig.hub.posts[-1][2]["events"][0]["fields"]["actor"] == "ana"

    assert _put(rig, {"opt_in": False})[1]["names"] is False
    assert rig.opt_in.get() is False
    rig.move("T-2", actor="ana")
    rig.forwarder().step()
    assert all("actor" not in e["fields"] for e in rig.hub.posts[-1][2]["events"])


@pytest.mark.parametrize("body", [{}, {"opt_in": "yes"}, {"opt_in": 1}, [], "true"])
def test_a_put_that_is_not_a_boolean_opt_in_is_a_400_and_changes_nothing(rig: Rig, body: object) -> None:
    status, answer = _put(rig, body)

    assert status == 400 and "opt_in" in answer["error"]
    assert rig.opt_in.get() is False


def test_a_put_that_is_not_json_is_a_400(rig: Rig) -> None:
    assert forwarding("127.0.0.1", "PUT", b"opt in please", rig.forwarder())[0] == 400


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_a_browser_off_the_private_network_is_refused_and_changes_nothing(rig: Rig, method: str) -> None:
    status, body = forwarding("203.0.113.9", method, b'{"opt_in": true}', rig.forwarder())

    assert status == 403
    assert body == {"error": "Forwarding answers only loopback and private network (RFC 1918) browsers"}
    assert rig.opt_in.get() is False


def _call(server, method: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        url(server, "/api/forwarding"),
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as err:
        return err.code, json.load(err)


def test_the_server_answers_get_and_put_on_the_forwarding_route(tmp_path: Path, rig: Rig) -> None:
    rig.move("T-1", actor="ana")

    with serve(tmp_path, forwarding=rig.forwarder()) as server:
        status, body = _call(server, "GET")
        assert (status, body["configured"], body["names"], len(body["next"])) == (200, True, False, 1)
        assert _call(server, "PUT", b'{"opt_in": true}')[1]["names"] is True
        assert _call(server, "GET")[1]["next"][0]["fields"]["actor"] == "ana"
        assert _call(server, "PUT", b'{"opt_in": false}')[1]["next"][0]["fields"].get("actor") is None


def test_a_serve_without_a_forwarder_answers_not_configured(tmp_path: Path) -> None:
    with serve(tmp_path) as server:
        assert _call(server, "GET") == (200, {"configured": False})


def test_a_write_from_another_page_or_not_as_json_is_refused_and_changes_nothing(tmp_path: Path, rig: Rig) -> None:
    with serve(tmp_path, forwarding=rig.forwarder()) as server:
        assert _call(server, "PUT", b'{"opt_in": true}', {"Origin": "http://evil.example"})[0] == 403
        assert _call(server, "PUT", b'{"opt_in": true}', {"Content-Type": "text/plain"})[0] == 415

    assert rig.opt_in.get() is False


def test_a_delete_of_the_forwarding_route_is_a_404(tmp_path: Path, rig: Rig) -> None:
    rig.opt_in.set(True)

    with serve(tmp_path, forwarding=rig.forwarder()) as server:
        request = urllib.request.Request(url(server, "/api/forwarding"), data=b"{}", method="DELETE")
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request)

    assert refused.value.code == 404
    assert rig.opt_in.get() is True


def test_the_contract_lists_the_lane_streams_fields_and_marks_the_assignee_as_a_person(rig: Rig) -> None:
    status, body = forwarding("127.0.0.1", "GET", b"", rig.forwarder())

    assert status == 200
    lanes = body["contract"]["board:lanes"]
    assert [entry["field"] for entry in lanes] == ["task", "lane", "time", "team", "milestone", "labels", "assignee"]
    assert [entry["field"] for entry in lanes if entry["person"]] == ["assignee"]
    assert "title" not in {entry["field"] for entry in lanes}
