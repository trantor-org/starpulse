"""A GET the server answered with an empty reply (a restart closed the connection before a byte) is sent once more
(TASK-11192); a second empty reply, and any other failure, is the unavailable error it always was."""

import http.client
import io
import urllib.request

import pytest
from starpulse.cli import agent_wire
from starpulse.cli.agent_wire import CliError


class _Reply(io.BytesIO):
    status = 200

    def __enter__(self) -> "_Reply":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _urlopen(monkeypatch: pytest.MonkeyPatch, outcomes: list[BaseException | _Reply]) -> list[int]:
    sent: list[int] = []

    def urlopen(request, timeout=None):
        sent.append(1)
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return sent


def test_an_empty_reply_is_sent_again_once(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _urlopen(monkeypatch, [http.client.RemoteDisconnected("empty"), _Reply(b'{"flows": []}')])

    assert agent_wire.get("http://x", "/api/snapshot") == (200, {"flows": []})
    assert len(sent) == 2


def test_a_second_empty_reply_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _urlopen(monkeypatch, [http.client.RemoteDisconnected("empty"), ConnectionResetError("reset")])

    with pytest.raises(CliError) as raised:
        agent_wire.get("http://x", "/api/snapshot")

    assert raised.value.code == "unavailable"
    assert len(sent) == 2


def test_a_refused_connection_is_not_sent_again(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _urlopen(monkeypatch, [ConnectionRefusedError("refused"), _Reply(b"{}")])

    with pytest.raises(CliError):
        agent_wire.get("http://x", "/api/snapshot")

    assert len(sent) == 1
