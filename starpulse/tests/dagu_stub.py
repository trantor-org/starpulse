"""A Dagu API on an ephemeral port that counts the requests it gets, and `runs:events` entries as a consumer reads them."""

import itertools
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_ids = itertools.count(1)  # Redis stream ids rise; each entry built here takes the next


@contextmanager
def dagu(
    steps: dict[str, list[str]], labels: dict[str, str] | None = None, latest: dict[str, str] | None = None
) -> Iterator[tuple[str, list[str]]]:
    """Serve one DAG per key of `steps` (its value is the step names, each depending on the one before).

    A step reports `succeeded` in the latest run unless `labels` (read at each request) names its label.
    The listing gives every DAG the `latest` run (a dict the caller may change while the server runs), a
    succeeded `r0` unless given. Yields the base URL and the list of every request path received, in order.
    """
    calls: list[str] = []
    step_labels: dict[str, str] = {} if labels is None else labels
    run: dict[str, str] = {"statusLabel": "succeeded", "dagRunId": "r0"} if latest is None else latest

    def detail(name: str) -> dict:
        return {
            "dag": {"steps": [{"name": s, "depends": steps[name][i - 1 : i]} for i, s in enumerate(steps[name])]},
            "latestDAGRun": {
                "nodes": [{"step": {"name": s}, "statusLabel": step_labels.get(s, "succeeded")} for s in steps[name]]
            },
        }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            calls.append(self.path)
            if self.path == "/api/v1/dags?perPage=200":
                listing = {"dags": [{"fileName": n, "latestDAGRun": {**run}} for n in steps]}
                body = json.dumps(listing)
            else:
                body = json.dumps(detail(self.path.rsplit("/", 1)[1]))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()


def run_entry(phase: str, workflow: str, run_id: str, status: str, at: float) -> tuple:
    """`(stream id, fields)` for one `runs:events` entry, its values strings as `StreamProducer` writes them."""
    fields = {"event_id": f"{workflow}-{run_id}-{phase}", "time": str(at), "phase": phase, "workflow": workflow}
    fields |= {"run_id": run_id, "status": status}
    return f"{next(_ids)}-0", fields
