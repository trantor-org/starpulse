"""The serving process asks the kernel for a short scheduling slice, so a request that wakes behind a CPU hog waits
microseconds, not a hog's whole slice: the Page API's p95 at host load 100+ was run-queue delay, not read cost."""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest
from starpulse.runtime import sched, worker
from starpulse.views.bin import api_worker


def slice_ns() -> int:
    """This thread's EEVDF slice, as the kernel reports it in /proc/thread-self/sched."""
    with open("/proc/thread-self/sched") as report:
        lines = [line for line in report if line.startswith("se.slice")]
    return int(lines[0].split(":")[1])


def in_thread(work: Callable[[], object]) -> object:
    """Run `work` on a fresh thread so the test leaves the pytest main thread's scheduling alone."""
    out: list[object] = []
    thread = threading.Thread(target=lambda: out.append(work()))
    thread.start()
    thread.join()
    return out[0]


def test_shorten_slice_sets_the_calling_thread_and_the_threads_it_starts() -> None:
    def work() -> tuple[bool, int, int]:
        applied = sched.shorten_slice(100_000)
        return applied, slice_ns(), int(in_thread(slice_ns))  # type: ignore[call-overload]

    applied, own, child = in_thread(work)  # type: ignore[misc]
    assert (applied, own, child) == (True, 100_000, 100_000)


def test_shorten_slice_reports_a_kernel_refusal_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sched, "_syscall", lambda *args: -1)
    assert sched.shorten_slice(100_000) is False


def test_the_api_worker_shortens_its_slice_before_it_builds_the_page(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(sched, "shorten_slice", lambda: calls.append("slice") or True)
    monkeypatch.setattr(api_worker, "main", lambda argv, parser, *, host: calls.append("page"))
    worker.main(["api"])
    assert calls == ["slice", "page"]
