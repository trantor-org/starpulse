"""Load a running StarPulse with many viewers at once and fail on a route whose p95 leaves the budget.

`page_latency.py` times one viewer; this is the same budget under a crowd. Each simulated viewer does what an open
page does: it holds the event stream open (`/api/events?snapshot=ref`), reads the snapshot body the first event names,
and then reads the page's `/api` routes at a viewer's pace. Locust reports each route's p50, p95 and p99, and the
stream's connect-to-first-snapshot as `/api/events first snapshot`; a route whose p95 is over 50 ms, or that failed
once, exits the run 1. A connect whose snapshot differs from the last viewer's overlapped a feed change and may have
waited out the server's one rebuild for it; it is reported as `/api/events first snapshot after change` and not judged.

    uv run --group bench locust -f bench/load.py --host http://127.0.0.1:8766 --headless -u 50 -r 5 -t 2m

Drop `--headless` for Locust's web UI on port 8089, which charts the same numbers live while the crowd ramps.
The stream holds a server thread per viewer for the
whole run, so the user count is also the number of concurrent streams.
"""

from __future__ import annotations

import http.client
import random
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager

from page_latency import BUDGET_MS, READS, connection, fill, ids_of, ref_key

#: The stream's first snapshot, as Locust names it among the routes.
FIRST_SNAPSHOT = "/api/events first snapshot"
#: The same, for a connect whose snapshot differs from the last viewer's: it overlapped a feed change, so it may have
#: waited out the one rebuild the server makes per change. Locust reports it; the verdict does not judge it.
FIRST_SNAPSHOT_AFTER_CHANGE = "/api/events first snapshot after change"
#: A read the stream's own snapshot reference makes, not one a viewer picks.
BODY = "/api/events/body/<id>"
#: The reads each viewer makes once to find this server's records and routes; they are setup, not a viewer's load.
DISCOVERY = "discovery"


def events(lines: Iterable[bytes]) -> Iterator[tuple[str, str]]:
    """Each `(event, data)` an event stream's lines dispatch; an event cut off before its blank line yields nothing."""
    event, data = "message", []
    for raw in lines:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())


def over_budget(p95s: Mapping[str, float], failures: Mapping[str, int], budget: float = BUDGET_MS) -> list[str]:
    """Why the run fails: each route over `budget` at p95 or with a failed request; Locust's `Aggregated` row and the
    discovery reads are not routes."""
    reasons = []
    for name, p95 in sorted(p95s.items()):
        if name in ("Aggregated", DISCOVERY):
            continue
        if failures.get(name):
            reasons.append(f"{name} {failures[name]} failed")
        elif p95 > budget and name != FIRST_SNAPSHOT_AFTER_CHANGE:
            reasons.append(f"{name} p95 {p95:.0f} ms > {budget:.0f} ms")
    return reasons


class Changes:
    """Whether a snapshot's key differs from the last one seen: the feed changed between two viewers' connects."""

    def __init__(self) -> None:
        self._last: str | None = None

    def seen(self, key: str | None) -> bool:
        changed = self._last is not None and key is not None and key != self._last
        self._last = key or self._last
        return changed


class Once[T]:
    """A value the first caller makes; a caller arriving while it is being made waits for it instead of making it too.
    Viewers spawn while the first is still discovering, and each one that discovered again parsed the whole snapshot in
    this process during the ramp, which the stream rows then timed."""

    def __init__(self, lock: AbstractContextManager) -> None:
        self._lock, self._made, self._value = lock, False, None

    def get(self, make: Callable[[], T]) -> T:
        with self._lock:
            if not self._made:
                self._value, self._made = make(), True
        return self._value  # type: ignore[return-value]


def compressed_body(base: str, path: str) -> tuple[int, int]:
    """`path`'s status and the bytes it sent, asked for gzip and left compressed. A viewer's browser inflates the body
    on the viewer's machine; inflating a crowd's worth here would time this process, not the server (the snapshot's
    5 MB takes ~28 ms of the one thread every viewer shares, which is what its own p50 and p95 then measured)."""
    conn = connection(base)
    try:
        conn.request("GET", path, headers={"accept-encoding": "gzip"})
        response = conn.getresponse()
        return response.status, len(response.read())
    finally:
        conn.close()


# Everything below needs Locust (the bench group); the rules above carry the tests.

try:
    import gevent
    import gevent.lock
    from locust import HttpUser, between, task
    from locust import events as locust_events
except ImportError:
    pass
else:

    @locust_events.quitting.add_listener
    def _verdict(environment, **_) -> None:
        entries = environment.stats.entries.values()
        reasons = over_budget(
            {e.name: e.get_response_time_percentile(0.95) or 0.0 for e in entries},
            {e.name: e.num_failures for e in entries},
        )
        for reason in reasons:
            print(f"OVER BUDGET {reason}")
        if reasons:
            environment.process_exit_code = 1

    class Viewer(HttpUser):
        """One open StarPulse page: a held event stream and the reads a viewer's clicks make."""

        wait_time = between(0.5, 2)
        paths: Once[dict[str, str]] = Once(gevent.lock.BoundedSemaphore())
        stream: gevent.Greenlet | None = None
        changes = Changes()

        def on_start(self) -> None:
            self.routes = Viewer.paths.get(self._paths)
            self.stream = gevent.spawn(self._watch)

        def on_stop(self) -> None:
            if self.stream:
                self.stream.kill(block=False)

        def _paths(self) -> dict[str, str]:
            """Each read route's path, filled from this server's own records; a route with none to read, or that does not
            answer 200 (a server with no milestones, docs or scheduler), is skipped."""

            def json(path: str) -> object:
                answer = self._probe(path)
                return answer.json() if answer is not None else {}

            snapshot = json("/api/snapshot")
            ids = ids_of(snapshot if isinstance(snapshot, dict) else {}, json("/api/milestones"), json("/api/docs"))
            filled = {name: fill(template, ids) for name, template in READS.items() if name != BODY}
            return {name: path for name, path in filled.items() if path and self._probe(path) is not None}

        def _probe(self, path: str):
            """`path`'s response when it answers 200, else None; a probe that does not is no failure of the run."""
            with self.client.get(path, name=DISCOVERY, catch_response=True) as response:
                response.success()
            return response if response.status_code == 200 else None

        def _watch(self) -> None:
            """Hold the stream open, as the page does, timing connect to the end of its first snapshot."""
            conn = connection(self.host)
            start, first = time.perf_counter(), True
            try:
                conn.request("GET", "/api/events?snapshot=ref", headers={"accept": "text/event-stream"})
                response = conn.getresponse()
                for event, data in events(iter(response.fp.readline, b"")):
                    if first and event == "snapshot":
                        first = False
                        key = ref_key(data)
                        after_change = Viewer.changes.seen(key)
                        self._fire(FIRST_SNAPSHOT_AFTER_CHANGE if after_change else FIRST_SNAPSHOT, start, None)
                        if key:
                            self._fetch(BODY, f"/api/events/body/{key}")
            except (http.client.HTTPException, OSError) as error:
                if first:
                    self._fire(FIRST_SNAPSHOT, start, error)
            finally:
                conn.close()

        def _fetch(self, name: str, path: str) -> None:
            """Read `path` as the viewer's browser would receive it, compressed, and time it as route `name`."""
            start, error = time.perf_counter(), None
            try:
                status, _ = compressed_body(self.host, path)
                error = None if status == 200 else http.client.HTTPException(f"{path} answered {status}")
            except (http.client.HTTPException, OSError) as failed:
                error = failed
            self._fire(name, start, error)

        def _fire(self, name: str, start: float, error: BaseException | None) -> None:
            self.environment.events.request.fire(
                request_type="SSE" if name.startswith(FIRST_SNAPSHOT) else "GET",
                name=name,
                response_time=(time.perf_counter() - start) * 1000,
                response_length=0,
                exception=error,
            )

        @task
        def read(self) -> None:
            name, path = random.choice(list(self.routes.items()))
            self._fetch(name, path)
