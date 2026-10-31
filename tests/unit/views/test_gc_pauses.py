"""An API worker collects garbage on a timer, not whenever an allocation trips the collector, and reports each pause.

On a free-threaded build a collection stops every thread, and under CPU contention the stop waits for descheduled
threads, so an automatic collection mid-request stalls the whole worker for tens of milliseconds to seconds.
"""

import gc
import threading
import weakref
from collections.abc import Iterator

import pytest

from starpulse.views.adapters.outbound.gc_pauses import GcPauses, install


@pytest.fixture
def pauses() -> Iterator[GcPauses]:
    was_enabled = gc.isenabled()
    ledger = GcPauses()
    yield ledger
    if ledger.callback in gc.callbacks:
        gc.callbacks.remove(ledger.callback)
    if was_enabled:
        gc.enable()


class _Cycle:
    def __init__(self) -> None:
        self.me = self


def test_install_turns_automatic_collection_off_and_a_stopped_event_ends_the_timer(pauses: GcPauses) -> None:
    stop = threading.Event()

    timer = install(stop, interval_s=3600.0, pauses=pauses)

    assert not gc.isenabled()
    stop.set()
    timer.join(timeout=5)
    assert not timer.is_alive()


def test_the_timer_frees_cyclic_garbage_that_automatic_collection_would_have_left(pauses: GcPauses) -> None:
    stop = threading.Event()
    garbage = _Cycle()
    ref = weakref.ref(garbage)
    del garbage

    timer = install(stop, interval_s=0.01, pauses=pauses)
    try:
        for _ in range(500):
            if ref() is None:
                break
            threading.Event().wait(0.01)
    finally:
        stop.set()
        timer.join(timeout=5)

    assert ref() is None


def test_each_collection_is_counted_and_its_pause_timed(pauses: GcPauses) -> None:
    gc.callbacks.append(pauses.callback)
    _Cycle()

    gc.collect()

    lines = pauses.exposition().splitlines()
    assert "starpulse_gc_collections_total 1" in lines
    assert any(line.startswith("starpulse_gc_pause_seconds_sum ") for line in lines)
    assert any(line.startswith("starpulse_gc_pause_seconds_max ") for line in lines)
    collected = next(line for line in lines if line.startswith("starpulse_gc_collected_total "))
    assert int(collected.split()[1]) >= 1
    assert "# TYPE starpulse_gc_collections_total counter" in lines


def test_a_worker_that_never_collected_reports_zero(pauses: GcPauses) -> None:
    assert "starpulse_gc_collections_total 0" in pauses.exposition().splitlines()
