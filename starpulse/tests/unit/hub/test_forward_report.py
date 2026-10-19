"""The forwarding worker's seam with `serve`: what the forwarder last did, kept in the event log."""

from pathlib import Path

import pytest

from starpulse._internal.config.config import Forward
from starpulse._internal.eventlog.event_log import EventLog, Tail
from starpulse._internal.eventlog.history import HistoryStore
from starpulse._internal.hub import forward_report
from starpulse._internal.hub.forward import Forwarder, OptIn


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        url = f"sqlite:///{(tmp_path / 'h.sqlite').resolve()}"
        self.log = EventLog(url)
        self.store = HistoryStore(url, {})
        self.forwarder = Forwarder(
            self.log, self.store, Forward("https://hub.example.test", "T"), "tok", OptIn(self.log)
        )

    def stream_head(self) -> int:
        return len(Tail(self.log, forward_report.REPORTED_STREAM, after=0).poll())


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def test_the_publisher_keeps_the_runtime_in_the_log_and_announces_only_a_change(rig: Rig) -> None:
    publish = forward_report.Publisher(rig.log, rig.forwarder)
    rig.forwarder.problem = "hub unreachable: down"

    publish()
    publish()

    assert rig.log.setting(forward_report.RUNTIME) == {
        "lastSent": None,
        "problem": "hub unreachable: down",
        "refused": False,
    }
    assert rig.stream_head() == 1
    rig.forwarder.problem = None
    publish()
    assert rig.stream_head() == 2


def test_serve_adopts_what_the_worker_kept_and_pushes_it(rig: Rig, tmp_path: Path) -> None:
    rig.forwarder.problem = "hub answered 503"
    rig.forwarder.last_sent = 12.5
    rig.forwarder._refused = True
    forward_report.Publisher(rig.log, rig.forwarder)()
    serving = Forwarder(
        rig.log, rig.store, Forward("https://hub.example.test", "T"), "tok", OptIn(rig.log)
    )
    pushed: list[int] = []

    forward_report.Reported(rig.log, serving, lambda: pushed.append(1)).apply()

    assert serving.problem == "hub answered 503"
    assert serving.last_sent == 12.5
    assert serving._refused is True
    assert pushed == [1]


def test_nothing_kept_yet_leaves_the_forwarder_as_it_was(rig: Rig) -> None:
    pushed: list[int] = []

    forward_report.Reported(rig.log, rig.forwarder, lambda: pushed.append(1)).apply()

    assert rig.forwarder.problem is None
    assert pushed == []
