"""The signals store a Loki instance gives `TelemetryLog` when the config names one (`telemetry_loki_url`).

One log line per signal, the signal's stored fields as JSON, in the stream `{job="starpulse-signals"}`. A line is
stamped with the time it was pushed, not the signal's own time, so a replayed export is never older than the stream's
window and a reader resumes after the last stamp it saw. Retention is the Loki instance's: give the stream its own
`retention_stream` rule to keep it as long as the instance keeps its event log.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator
from typing import Any

__all__ = ["LokiSignals"]

JOB = "starpulse-signals"
PAGE = 5000


class LokiSignals:
    """Pushes signals to Loki and reads them back in the order they were pushed."""

    def __init__(self, url: str, timeout: float = 10.0) -> None:
        self._url = url.rstrip("/")
        self._timeout = timeout
        self._last = 0

    def push(self, rows: Iterable[dict[str, Any]]) -> None:
        """Appends each row as one line; raises `OSError` when Loki cannot be reached or refuses the push."""
        values = []
        for row in rows:
            self._last = max(time.time_ns(), self._last + 1)
            values.append([str(self._last), json.dumps(row, separators=(",", ":"))])
        if not values:
            return
        body = json.dumps({"streams": [{"stream": {"job": JOB}, "values": values}]}).encode()
        request = urllib.request.Request(f"{self._url}/loki/api/v1/push", body, {"Content-Type": "application/json"})
        urllib.request.urlopen(request, timeout=self._timeout).close()

    def fetch(self, after: int) -> list[tuple[int, dict[str, Any]]]:
        """The `(stamp, row)` pairs stamped after `after` (nanoseconds), oldest first; raises `OSError` on a fault."""
        return [pair for page in self.pages(after) for pair in page]

    def pages(self, after: int) -> Iterator[list[tuple[int, dict[str, Any]]]]:
        """`fetch` one page at a time, so a reader folds a long history without holding every row at once."""
        while True:
            query = urllib.parse.urlencode(
                {
                    "query": f'{{job="{JOB}"}}',
                    "start": after + 1,
                    "end": time.time_ns() + 1,
                    "limit": PAGE,
                    "direction": "forward",
                }
            )
            with urllib.request.urlopen(
                f"{self._url}/loki/api/v1/query_range?{query}", timeout=self._timeout
            ) as response:
                streams = json.load(response)["data"]["result"]
            page = sorted((int(stamp), json.loads(line)) for stream in streams for stamp, line in stream["values"])
            yield page
            if len(page) < PAGE:
                return
            after = page[-1][0]
