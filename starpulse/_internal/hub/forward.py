"""What an IC sends a hub, and the filter that keeps a person's name at home.

The forwarder reads only the machine, runs and lane streams. Each entry is cut down to the fields the stream's contract
names (`FIELDS`), so a field a producer added never leaves the IC. `actor`, `profile` and `assignee` name a person, so they
leave only while the IC is opted in (`OptIn`).
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starpulse._internal.config.config import discover
from starpulse._internal.eventlog import lane_events
from starpulse._internal.runs.forwarded import FIELDS, PERSON, project

if TYPE_CHECKING:
    from starpulse._internal.config.config import Config, Forward
    from starpulse._internal.eventlog.event_log import EventLog
    from starpulse._internal.eventlog.history import HistoryStore

logger = logging.getLogger(__name__)

#: How many of the next entries the status lists; the rest are only counted as "more".
PREVIEW = 10

__all__ = ["FIELDS", "PERSON", "PREVIEW", "Forwarder", "OptIn", "build", "main", "post", "project", "start"]


KEY = "forward.opt_in"


class OptIn:
    """Whether this instance lets a person's name leave: the flag in the history store, off unless it says `true`.

    It is a setting, not config, so flipping it needs no restart and no hub: the forwarder reads it before every batch,
    and one that is missing or unreadable leaves the instance opted out.
    """

    def __init__(self, log: EventLog) -> None:
        self.log = log

    def get(self) -> bool:
        try:
            return self.log.setting(KEY) is True
        except Exception as exc:  # fail closed: an unreadable setting is an unset one
            logger.warning("settings: reading %s failed: %s", KEY, exc)
            return False

    def set(self, value: bool) -> None:
        self.log.set_setting(KEY, value)


#: How long one POST to the hub may take, and how long the forwarder rests when it has caught up.
TIMEOUT = 10.0
DEFAULT_INTERVAL = 5.0
#: How often the forwarder sends every task's current lane again, besides once at its start.
SNAPSHOT_EVERY = 24 * 3600.0
#: How long `GET /api/forwarding` answers the status it built before a background rebuild replaces it: each build is
#: four store reads, over the page's 50 ms budget, so no read waits on one once the first has been built.
STATUS_TTL = 2.0

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
        status_ttl: float = 0.0,
    ) -> None:
        self.log = log
        self.store = store
        self.forward = forward
        self.token = token
        self.opt_in = opt_in
        self.name = f"forward:{forward.url}"
        self.instance = store.instance(self.name)  # the hub binds the source's token to the first one it sees
        self.url = f"{forward.url.rstrip('/')}/api/forward"
        self.interval = interval
        self._send = send
        self._refused = False  # the hub took no opt-in; send names-free until the instance opts out and in again
        self._clock = clock
        self._snapshot_at: float | None = None  # when the hub last took this process's snapshot; None: not yet
        self.last_sent: float | None = None  # when the hub last acknowledged a batch, in this process
        self.problem: str | None = None  # why the last batch did not go through; None once one does
        self._status_ttl = status_ttl
        self._status: tuple[float, dict[str, Any]] | None = None  # when `status` built its last answer, and that answer
        self._status_epoch = 0  # bumped by `forget_status`, so a rebuild begun before it cannot restore the old answer
        self._rebuilding = threading.Lock()  # held while one background rebuild runs

    def step(self) -> int | None:
        """Send the next batch: how many entries the log held past the cursor, or None when it did not go through.

        The opt-in is read here, once per batch. Entries of streams that are not forwarded move the cursor and cost
        no request. A lane snapshot goes once the log is sent, when this process has not sent one or the last was a day ago.
        """
        opted = self.opt_in.get()
        if not opted:
            self._refused = False
        sent_opt_in = opted and not self._refused
        after = self.store.checkpoints.load(self.name)[0]

        tail = self.log.tail(self.name, streams=tuple(FIELDS), after=after, batch=self.forward.batch)
        entries = tail.poll()
        if not entries:
            if tail.cursor != after:
                self.store.checkpoints.save(self.name, tail.cursor)
            if self._snapshot_due() and not self._snapshot(sent_opt_in):
                return None
            return 0
        batch = [
            {"event_id": e.event_id, "stream": e.stream, "fields": project(e.stream, e.fields, opt_in=sent_opt_in)}
            for e in entries
        ]
        if not self._deliver(batch, sent_opt_in):
            return None
        self.store.checkpoints.save(self.name, tail.cursor)
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
        body = json.dumps({"opt_in": sent_opt_in, "instance": self.instance, "events": batch}).encode()
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
        cached = self._status
        if cached is None or not self._status_ttl:
            return self._rebuild_status()
        if time.monotonic() - cached[0] >= self._status_ttl and self._rebuilding.acquire(blocking=False):
            threading.Thread(target=self._refresh_status, daemon=True).start()
        return cached[1]

    def runtime(self) -> dict[str, Any]:
        """What this process learned of the hub, for another process to show: `adopt` takes it."""
        return {"lastSent": self.last_sent, "problem": self.problem, "refused": self._refused}

    def adopt(self, runtime: Mapping[str, Any]) -> None:
        """Take the `runtime` another process's forwarder kept, so `status` shows the worker's last send and refusal."""
        self.last_sent = runtime.get("lastSent")
        self.problem = runtime.get("problem")
        self._refused = bool(runtime.get("refused"))
        self.forget_status()

    def forget_status(self) -> None:
        """Drop the status kept for `status_ttl`, so the next read sees a change made now, such as a new opt-in."""
        self._status_epoch += 1
        self._status = None

    def _rebuild_status(self) -> dict[str, Any]:
        epoch = self._status_epoch
        built = self._build_status()
        if epoch == self._status_epoch:
            self._status = (time.monotonic(), built)
        return built

    def _refresh_status(self) -> None:
        try:
            self._rebuild_status()
        except Exception:  # the log or store failed; the next read after the ttl tries again
            logger.exception("Forwarder: status rebuild failed, serving the last one")
        finally:
            self._rebuilding.release()

    def _build_status(self) -> dict[str, Any]:
        opted = self.opt_in.get()
        names = opted and not self._refused

        tail = self.log.tail(
            self.name,
            streams=tuple(FIELDS),
            after=self.store.checkpoints.load(self.name)[0],
            batch=PREVIEW + 1,
        )
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

    def run(self, stop: threading.Event, after_step: Callable[[], None] | None = None) -> None:
        """Forward until `stop` is set: straight on while batches come back full, else rest for the interval.

        `after_step` runs after each step to report what the step learned of the hub.
        """
        while not stop.is_set():
            try:
                sent = self.step()
                if after_step:
                    after_step()
            except Exception:  # the log or store failed; the next step retries from the saved cursor
                logger.exception("Forwarder: step failed, retrying in %ss", self.interval)
                sent = None
            if sent != self.forward.batch:
                stop.wait(self.interval)


def main(argv: Sequence[str] | None = None) -> int:
    """`starpulse forward opt-in|opt-out|status|rebind`: set or show whether a person's name may leave this instance,
    or, on a hub, let another instance send under a source's token.

    The opt-in flag is a row in the store `--config` names (the working directory's `starpulse.toml` or the defaults
    without one), where the running server's forwarder reads it before every batch, so the change needs no restart and
    no hub. `rebind
    SOURCE` runs against the hub's own config: it drops the instance the hub bound SOURCE's token to, so the next
    batch under that token, from any instance, binds it again. It exits 1 for a source that held no binding.
    """
    parser = argparse.ArgumentParser(
        prog="starpulse forward",
        description="let a person's name leave this instance for the hub, or stop it; on a hub, rebind a source",
    )
    parser.add_argument("action", choices=("opt-in", "opt-out", "status", "rebind"))
    parser.add_argument("source", nargs="?", help="rebind: the `[[sources]]` name whose binding to drop")
    parser.add_argument(
        "--config",
        type=Path,
        help="the TOML config the server runs with; the flag is stored in the history store it names",
    )
    args = parser.parse_args(argv)
    if args.action == "rebind":
        if not args.source:
            parser.error("rebind needs the name of the source to rebind")
        from starpulse._internal.eventlog.history import open_event_log  # noqa: PLC0415 - the database stack loads when a log opens

        held = open_event_log(args.config).unbind_source(args.source)
        print(
            f"{args.source}: binding dropped; the next instance to send under its token takes it"
            if held
            else f"{args.source}: not bound; the first instance to send under its token takes it"
        )
        return 0 if held else 1
    if args.source:
        parser.error(f"{args.action} takes no source")
    config = discover(args.config)
    from starpulse._internal.eventlog.history import open_event_log  # noqa: PLC0415 - the database stack loads when a log opens

    flag = OptIn(open_event_log(config))
    if args.action != "status":
        flag.set(args.action == "opt-in")
    print(f"forward: {'opted in' if flag.get() else 'opted out'}")
    return 0


def build(
    config: Config, log: EventLog, store: HistoryStore, environ: Mapping[str, str], *, hub: bool = False
) -> Forwarder | None:
    """The forwarder `[forward]` configures; None without one.

    Raises `ValueError` for `[forward]` on a hub, which
    is an IC's setting, and for a `token_env` that names an unset variable.
    """
    if config.forward is None:
        return None
    if hub:
        raise ValueError("[forward] sends an IC's events to a hub; a hub does not forward")
    if not (token := environ.get(config.forward.token_env)):
        raise ValueError(f"[forward]: {config.forward.token_env} is not set")
    return Forwarder(log, store, config.forward, token, OptIn(log), status_ttl=STATUS_TTL)


def start(
    forwarder: Forwarder, stop: threading.Event, after_step: Callable[[], None] | None = None
) -> threading.Thread:
    """Run `forwarder` as a daemon thread that ends when `stop` is set."""
    thread = threading.Thread(target=forwarder.run, args=(stop, after_step), name="forwarder", daemon=True)
    thread.start()
    return thread
