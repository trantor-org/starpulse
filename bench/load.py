"""Load a running StarPulse with many viewers at once and fail on a route whose p95 leaves the budget.

`page_latency.py` times one viewer; this is the same budget under a crowd. Each simulated viewer does what an open
page does: it holds the event stream open (`/api/events?snapshot=ref`), reads the snapshot body the first event names,
and then reads the page's `/api` routes at a viewer's pace. Locust reports each route's p50, p95 and p99, and the
stream's connect-to-first-snapshot as `/api/events first snapshot`; a route whose p95 is over 50 ms, or that failed
once, exits the run 1.

    uv run --group bench locust -f bench/load.py --host http://127.0.0.1:8766 --headless -u 50 -r 5 -t 2m

Drop `--headless` for Locust's web UI on port 8089, which charts the same numbers live while the crowd ramps.
`--what-if FROM TO` names the two states `/api/level/what-if` asks about, as for `page_latency.py`; the seeded gate
server (`ci/seeded_server.py`) spells them `in_progress review`. The stream holds a server thread per viewer for the
whole run, so the user count is also the number of concurrent streams.
"""

from __future__ import annotations

import http.client
import random
import time
import urllib.parse
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager

from page_latency import BUDGET_MS, READS, WHAT_IF, fill, ids_of, ref_key

#: The stream's first snapshot, as Locust names it among the routes.
FIRST_SNAPSHOT = "/api/events first snapshot"
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
        elif p95 > budget:
            reasons.append(f"{name} p95 {p95:.0f} ms > {budget:.0f} ms")
    return reasons


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


def compressed_body(host: str, port: int, path: str) -> tuple[int, int]:
    """`path`'s status and the bytes it sent, asked for gzip and left compressed. A viewer's browser inflates the body
    on the viewer's machine; inflating a crowd's worth here would time this process, not the server."""
    conn = http.client.HTTPConnection(host, port, timeout=60)
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

    @locust_events.init_command_line_parser.add_listener
    def _options(parser) -> None:
        parser.add_argument("--what-if", nargs=2, default=list(WHAT_IF), help="the states the what-if reads")

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

        def on_start(self) -> None:
            self.routes = Viewer.paths.get(self._paths)
            self.stream = gevent.spawn(self._watch)

        def on_stop(self) -> None:
            self.stream.kill(block=False)

        def _paths(self) -> dict[str, str]:
            """Each read route's path, filled from this server's own records; a route with none to read, or that does not
            answer 200 (the seeded server has no milestones or docs), is skipped."""

            def json(path: str) -> object:
                answer = self._probe(path)
                return answer.json() if answer is not None else {}

            snapshot = json("/api/snapshot")
            ids = ids_of(snapshot if isinstance(snapshot, dict) else {}, json("/api/milestones"), json("/api/docs"))
            ids |= dict(zip(("from", "to"), self.environment.parsed_options.what_if, strict=True))
            filled = {name: fill(template, ids) for name, template in READS.items() if name != BODY}
            return {name: path for name, path in filled.items() if path and self._probe(path) is not None}

        def _probe(self, path: str):
            """`path`'s response when it answers 200, else None; a probe that does not is no failure of the run."""
            with self.client.get(path, name=DISCOVERY, catch_response=True) as response:
                response.success()
            return response if response.status_code == 200 else None

        def _watch(self) -> None:
            """Hold the stream open, as the page does, timing connect to the end of its first snapshot."""
            parts = urllib.parse.urlsplit(self.host)
            address = parts.hostname or "127.0.0.1", parts.port or 80
            conn = http.client.HTTPConnection(*address, timeout=60)
            start, first = time.perf_counter(), True
            try:
                conn.request("GET", "/api/events?snapshot=ref", headers={"accept": "text/event-stream"})
                response = conn.getresponse()
                for event, data in events(iter(response.fp.readline, b"")):
                    if first and event == "snapshot":
                        first = False
                        self._fire(FIRST_SNAPSHOT, start, None)
                        if key := ref_key(data):
                            self._body(*address, f"/api/events/body/{key}")
            except (http.client.HTTPException, OSError) as error:
                if first:
                    self._fire(FIRST_SNAPSHOT, start, error)
            finally:
                conn.close()

        def _body(self, host: str, port: int, path: str) -> None:
            start, error = time.perf_counter(), None
            try:
                status, _ = compressed_body(host, port, path)
                error = None if status == 200 else http.client.HTTPException(f"{path} answered {status}")
            except (http.client.HTTPException, OSError) as failed:
                error = failed
            self._fire(BODY, start, error)

        def _fire(self, name: str, start: float, error: BaseException | None) -> None:
            self.environment.events.request.fire(
                request_type="SSE" if name == FIRST_SNAPSHOT else "GET",
                name=name,
                response_time=(time.perf_counter() - start) * 1000,
                response_length=0,
                exception=error,
            )

        @task
        def read(self) -> None:
            name, path = random.choice(list(self.routes.items()))
            self.client.get(path, name=name, headers={"accept": "application/json"})
