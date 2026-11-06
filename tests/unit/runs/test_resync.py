from __future__ import annotations

import threading
from pathlib import Path

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.wake import StopEvent
from starpulse.runs.adapters.outbound.resync import follow_resync
from starpulse.runs.model.run_events import RESYNC


def test_a_resync_naming_the_instance_runs_its_relist_and_another_instances_does_not(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'log.sqlite'}")
    stop = StopEvent()
    relisted = threading.Event()
    calls: list[int] = []
    follow_resync(log, "dagu", lambda: (calls.append(1), relisted.set()), stop)

    log.publish(RESYNC, {"instance": "gha"})
    log.publish(RESYNC, {"instance": "dagu"})

    assert relisted.wait(5)
    stop.set()
    assert calls == [1]
