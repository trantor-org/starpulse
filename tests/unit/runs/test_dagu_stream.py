from __future__ import annotations

import threading

from starpulse.event_log.wake import StopEvent
from starpulse.runs.adapters.outbound.dagu_stream import changes, follow_stream

_CONTROL = ['event: control\n', 'data: {"subscribed":["dagruns:all="]}\n', "\n"]
_MESSAGE = ["id: 2\n", "event: message\n", 'data: {"payload":{}}\n', "\n"]
_HEARTBEAT = [": heartbeat\n", "\n"]


def test_a_message_event_is_a_change_and_a_control_or_heartbeat_is_not() -> None:
    body = [*_CONTROL, *_MESSAGE, *_HEARTBEAT, *_MESSAGE]

    assert len(list(changes(body))) == 2


def test_each_change_calls_back_and_a_dropped_stream_is_opened_again() -> None:
    stop = StopEvent()
    opened: list[str] = []
    seen = threading.Event()
    calls: list[int] = []

    def lines(url: str):
        opened.append(url)
        if len(opened) == 1:
            raise OSError("refused")
        yield from [*_CONTROL, *_MESSAGE]

    def on_change() -> None:
        calls.append(1)
        seen.set()
        stop.set()

    follow_stream("http://dagu", on_change, stop, lines=lines, retry=0)
    assert seen.wait(5)
    assert (len(opened), len(calls)) == (2, 1)
    assert opened[0].endswith("/api/v1/events/stream?topics=dagruns%3Aall")
