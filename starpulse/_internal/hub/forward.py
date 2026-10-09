"""What an IC sends a hub, and the filter that keeps a person's name at home.

The forwarder reads only the machine, runs and lane streams. Each entry is cut down to the fields the stream's contract
names (`FIELDS`), so a field a producer added never leaves the IC. `actor` and `assignee` name a person, so they
leave only while the IC is opted in (`OptIn`).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starpulse._internal.runs.forwarded import FIELDS, PERSON, project
from starpulse._internal.eventlog import lane_events
from starpulse._internal.eventlog.event_log import EventLog, Tail

if TYPE_CHECKING:
    from starpulse._internal.config.config import Config, Forward
    from starpulse._internal.eventlog.history import HistoryStore

logger = logging.getLogger(__name__)

#: How many of the next entries the status lists; the rest are only counted as "more".
PREVIEW = 10

__all__ = ["FIELDS", "OPT_IN_FILE", "PERSON", "PREVIEW", "Forwarder", "OptIn", "build", "main", "post", "project", "start"]


#: Where the opt-in lives, in the directory of the `--config` file (the working directory without one).
OPT_IN_FILE = "starpulse-forward.json"


class OptIn:
    """Whether this instance lets a person's name leave: the flag in `path`, off unless the file says `true`.

    It is a file, not config, so flipping it needs no restart and no hub: the forwarder reads it before every batch,
    and a file that is missing or unreadable leaves the instance opted out.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self) -> bool:
        try:
            return json.loads(self.path.read_text())["opt_in"] is True
        except OSError, ValueError, KeyError, TypeError:
            return False

    def set(self, value: bool) -> None:
        scratch = self.path.with_name(f"{self.path.name}.tmp")
        scratch.write_text(json.dumps({"opt_in": value}))
        os.replace(scratch, self.path)  # a reader sees the old file or the new one, never half of one


#: How long one POST to the hub may take, and how long the forwarder rests when it has caught up.
TIMEOUT = 10.0
DEFAULT_INTERVAL = 5.0
#: How often the forwarder sends every task's current lane again, besides once at its start.
SNAPSHOT_EVERY = 24 * 3600.0

Send = Callable[[str, str, bytes], tuple[int, dict[str, Any]]]


def post(url: str, token: str, body: bytes) -> tuple[int, dict[str, Any]]:
    """POST `body` to `url` under `token`: `(status, JSON answer)`. A hub that cannot be reached raises `OSError`."""
    request = urllib.request.Request(
        url, data=body, method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            status, raw = answer.status, answer.read()
    except urllib.error.HTTPError as refusal:
        status, raw = refusal.code, refusal.read()
    try:
        decoded = json.loads(raw)
    except ValueError:
        return status, {}
    return status, decoded if isinstance(decoded, dict) else {}


class Forwarder:
    """Sends this IC's machine, runs and lane events to a hub, a batch at a time, in log order.

    It is a reader of the event log, not a Redis consumer: its cursor (the log id of the last entry the hub
    acknowledged) lives in the IC's store under `forward:<hub url>`, and moves only after the hub answers 200. A
    batch is never kept: each attempt rebuilds it from the log past the cursor, so a batch that failed while the
    instance was opted in goes out without names once it opts out. A send that dies between the hub's write and its
    answer repeats the batch, which the hub drops because it stores each `event_id` once.
    """

    def __init__(
        self,
        log: EventLog,
        store: HistoryStore,
        forward: Forward,
        token: str,
        opt_in: OptIn,
        *,
        send: Send = post,
        interval: float = DEFAULT_INTERVAL,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.log = log
        self.store = store
        self.forward = forward
        self.token = token
        self.opt_in = opt_in
        self.name = f"forward:{forward.url}"
        self.url = f"{forward.url.rstrip('/')}/api/forward"
        self.interval = interval
        self._send = send
        self._refused = False  # the hub took no opt-in; send names-free until the instance opts out and in again
        self._clock = clock
        self._snapshot_at: float | None = None  # when the hub last took this process's snapshot; None: not yet
        self.last_sent: float | None = None  # when the hub last acknowledged a batch, in this process
        self.problem: str | None = None  # why the last batch did not go through; None once one does

    def step(self) -> int | None:
        """Send the next batch: how many entries the log held past the cursor, or None when it did not go through.

        The opt-in is read here, once per batch. Entries of streams that are not forwarded move the cursor and cost
        no request. A lane snapshot goes once the log is sent, when this process has not sent one or the last was a day ago.
        """
        opted = self.opt_in.get()
        if not opted:
            self._refused = False
        sent_opt_in = opted and not self._refused
        after = self.store.cursor(self.name)
        tail = Tail(self.log, self.name, streams=tuple(FIELDS), after=after, batch=self.forward.batch)
        entries = tail.poll()
        if not entries:
            if tail.cursor != after:
                self.store.save_cursor(self.name, tail.cursor)
            if self._snapshot_due() and not self._snapshot(sent_opt_in):
                return None
            return 0
        batch = [
            {"event_id": e.event_id, "stream": e.stream, "fields": project(e.stream, e.fields, opt_in=sent_opt_in)}
            for e in entries
        ]
        if not self._deliver(batch, sent_opt_in):
            return None
        self.store.save_cursor(self.name, tail.cursor)
        return len(entries)

    def _snapshot_due(self) -> bool:
        return self._snapshot_at is None or self._clock() - self._snapshot_at >= SNAPSHOT_EVERY

    def _snapshot(self, sent_opt_in: bool) -> bool:
        """Send every task's current lane as lane entries under the ids of the changes that put it there, a batch at a
        time: True when the hub took them all. The hub folds an id it holds, or a lane the task is already in, as no
        change, so a snapshot sent again adds no lane-change row. It goes only once the log is sent, so a lane
        change the hub lacks never arrives after a newer one."""
        lanes = self.store.current_lanes()
        for start in range(0, len(lanes), self.forward.batch):
            batch = [
                {"event_id": event_id, "stream": lane_events.STREAM, "fields": {"task": task, "lane": lane, "time": at}}
                for event_id, task, lane, at in lanes[start : start + self.forward.batch]
            ]
            if not self._deliver(batch, sent_opt_in):
                return False
        self._snapshot_at = self._clock()
        return True

    def _deliver(self, batch: list[dict[str, Any]], sent_opt_in: bool) -> bool:
        """POST `batch` to the hub: True when it answered 200, else why not goes to `problem` and the log."""
        body = json.dumps({"opt_in": sent_opt_in, "events": batch}).encode()
        try:
            status, answer = self._send(self.url, self.token, body)
        except OSError as exc:
            logger.warning("Forwarder: %s unreachable, retrying: %s", self.url, exc)
            self.problem = f"hub unreachable: {exc}"
            return False
        if status != 200:
            if status == 403 and sent_opt_in:
                self._refused = True
            logger.warning("Forwarder: %s answered %s, retrying: %s", self.url, status, answer.get("error", ""))
            self.problem = f"hub answered {status}" + (f": {answer['error']}" if answer.get("error") else "")
            return False
        self.last_sent = self._clock()
        self.problem = None
        return True

    def status(self) -> dict[str, Any]:
        """What the next batch would send and why, for the instance's own page: the JSON body of `GET /api/forwarding`.

        `next` is the first `PREVIEW` entries past the cursor, cut by `project()` with the opt-in `step` would use, so
        the page lists the fields the hub is about to get, not a second reading of the contract; `kept` names the
        fields of an entry that stay on the instance. `names` is whether a person's name leaves in that batch: an
        opt-in a hub refused (`refused`) does not. Reading the log can note the same gap `step` would.
        """
        opted = self.opt_in.get()
        names = opted and not self._refused
        tail = Tail(self.log, self.name, streams=tuple(FIELDS), after=self.store.cursor(self.name), batch=PREVIEW + 1)
        entries = tail.poll()
        return {
            "url": self.url,
            "optIn": opted,
            "names": names,
            "refused": opted and self._refused,
            "lastSent": self.last_sent,
            "problem": self.problem,
            "next": [
                {
                    "stream": e.stream,
                    "fields": project(e.stream, e.fields, opt_in=names),
                    "kept": sorted(set(e.fields) - set(FIELDS[e.stream])),
                }
                for e in entries[:PREVIEW]
            ],
            "more": len(entries) > PREVIEW,
            "contract": {
                stream: [{"field": field, "person": field in PERSON} for field in fields]
                for stream, fields in FIELDS.items()
            },
        }

    def run(self, stop: threading.Event) -> None:
        """Forward until `stop` is set: straight on while batches come back full, else rest for the interval."""
        while not stop.is_set():
            try:
                sent = self.step()
            except Exception:  # the log or store failed; the next step retries from the saved cursor
                logger.exception("Forwarder: step failed, retrying in %ss", self.interval)
                sent = None
            if sent != self.forward.batch:
                stop.wait(self.interval)


def main(argv: Sequence[str] | None = None) -> int:
    """`starpulse forward opt-in|opt-out|status`: set or show whether a person's name may leave this instance.

    The flag is `OPT_IN_FILE` in the directory of `--config` (the working directory without one), where the running
    server's forwarder reads it before every batch, so the change needs no restart and no hub.
    """
    parser = argparse.ArgumentParser(
        prog="starpulse forward", description="let a person's name leave this instance for the hub, or stop it"
    )
    parser.add_argument("action", choices=("opt-in", "opt-out", "status"))
    parser.add_argument(
        "--config", type=Path, help="the TOML config the server runs with; the flag is stored beside it"
    )
    args = parser.parse_args(argv)
    flag = OptIn((args.config.parent if args.config else Path.cwd()) / OPT_IN_FILE)
    if args.action != "status":
        flag.set(args.action == "opt-in")
    print(f"{flag.path}: {'opted in' if flag.get() else 'opted out'}")
    return 0


def build(
    config: Config, base: Path, log: EventLog, store: HistoryStore, environ: Mapping[str, str], *, hub: bool = False
) -> Forwarder | None:
    """The forwarder `[forward]` configures; None without one.

    `base` is the config's directory, where the opt-in file lives. Raises `ValueError` for `[forward]` on a hub, which
    is an IC's setting, and for a `token_env` that names an unset variable.
    """
    if config.forward is None:
        return None
    if hub:
        raise ValueError("[forward] sends an IC's events to a hub; a hub does not forward")
    if not (token := environ.get(config.forward.token_env)):
        raise ValueError(f"[forward]: {config.forward.token_env} is not set")
    return Forwarder(log, store, config.forward, token, OptIn(base / OPT_IN_FILE))


def start(forwarder: Forwarder, stop: threading.Event) -> threading.Thread:
    """Run `forwarder` as a daemon thread that ends when `stop` is set."""
    thread = threading.Thread(target=forwarder.run, args=(stop,), name="forwarder", daemon=True)
    thread.start()
    return thread
