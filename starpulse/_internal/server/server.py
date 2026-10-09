"""Serve StarPulse: every lifecycle machine, the tasks in each, and the workflows of each runs adapter instance.

    .venv/bin/python -m starpulse._internal.server.server [--host 127.0.0.1] [--port 8766] [--hours 6] [--config starpulse.toml]

Every write (POST /api/..., PUT /api/forwarding, PUT /api/autopilot, PUT and DELETE /api/history-window) must be `Content-Type: application/json` (else 415) and carry
no `Origin` or this server's own (else 403), so a web page on another site cannot write through the operator's browser.
It listens on --host, 127.0.0.1 by default.

GET /auth/login, /auth/callback
                   a hub's sign-in (`serve --hub`; an IC instance has no sign-in): login sends the browser to the OpenID
                   Connect issuer, the callback finishes the sign-in with a session cookie and sends it to /, or
                   answers 403 naming why an account outside `allowed_groups` was refused. Every other route of a hub,
                   this one included, answers 401 until then; a bearer token is no session (see POST /api/runs/events),
                   except that a GET or HEAD carrying the hub's reader token (`reader_token_env`) is served
GET /              the page, built by `pnpm --filter flow-view build` into static/: one view
                   that drills Board → Board state → machine, or Board → workflow. It holds one
                   /api/events connection and nothing else
GET /board, /flow/<name>, /runs
                   the same page; it opens the level that draws that graph, then rewrites the address to /
GET /?demo         the page driven by synthetic agents, for a look without live data
GET /api/events    server-sent events: a `snapshot` on connect ({graphs, dags, pools, flows: [{name,
                   machine, agents}], pulls, settled, error, now}: every machine with its tasks, the
                   workflow declarations, the workflows, each named `<instance>/<workflow>`, and the
                   concurrency pools they run on, each named `<instance>/<pool>`), then
                   a `task` delta ({id, agent, settled}) per Board task change, a `move` delta ({flow, id, agent}) per task a machine placed, a
                   `dags` delta ({dags, pools, error}) per runs change, a `pulls` delta ({pulls}) per
                   change to a task's pull requests and a `claim` delta ({task, reason, at}) per
                   refused agent claim the board adapter reports, an `insight` delta ({id, finding}) per finding
                   an engine posts or retracts (`finding` null), with a `: ping` comment every 15 s.
                   `pulls` maps each open task that cites a pull request to [{number, url, checks
                   (pass, failing, pending, none), merged, merge_sha, merged_at (null until merged), threads (unresolved), behind_main (commits main holds that the head lacks; null once the head branch is gone), stale}], read from
                   GitHub through `gh` once a minute and held between reads; a failed read keeps the
                   last value with `stale` true.
                   Everything is held in memory: the Board from the configured board adapter, other machines' tasks
                   from machine:events, each instance's workflows from its adapter (`pushed/`: runs:events)
                   `?snapshot=ref` sends the `snapshot` as `ref /api/events/body/<key>`, the path its document is read
                   from, so a browser parses it off its main thread rather than as one long event.
GET /api/events/body/<key>
                   the `snapshot` document a `ref` named, cacheable for an hour (its key is its digest); 404 once the
                   server has built four newer ones
GET /api/snapshot  the document /api/events sends on connect, as one response, for `starpulse snapshot|board|task`
GET /api/merges[?before=T][&limit=N]
                   {merges, more}: the merge ledger's next `limit` rows (default 20, at most 100) older than `before`
                   (epoch seconds, the `at` of the last row held; none: the newest), each as the snapshot's
                   `ledgers.MERGED` row. None is older than 24 hours, `more` says whether older ones remain, and
                   rows sharing the boundary second all come in one page, so walking `before` neither repeats nor
                   skips a merge. A `before` that is not a finite number, or a `limit` outside 1-100, is 400
GET /api/pulls[?repo=OWNER/NAME][&number=N][&state=open|merged|closed][&body_contains=TEXT]
                   {pulls}: the pull requests the PR store read from GitHub (one query per repository a minute, the
                   open ones every time, a merged or closed one until it is final, a merged one also until it has its mergeSha), those matching every filter
                   given, by repository then number, each {repo, number, state (OPEN, MERGED, CLOSED), isDraft,
                   mergeable, baseRefName, headRefOid, body, checks (pass, failing, pending, none: the required
                   checks at the head commit), requiredChecks [{name, result}], threads (unresolved), updatedAt,
                   mergedAt and mergeSha (ISO 8601 UTC merge time and merge commit; null until merged, and for a
                   merge stored before they were kept), and fetchedAt (epoch seconds this record was read)}. A `number` that is not an integer, or a `state`
                   that is none of those, is 400
GET /metrics       Prometheus text: `starpulse_pull_store_age_seconds{repo}`, the seconds since the newest record of
                   each repository holding an open pull request was read; a stale one means the refresh stopped
GET /api/doctor    {ok, checks}: the `cue:` and `repo:` checks of `starpulse doctor` against this server's snapshot and config,
                   each {check, status (pass, warn, fail), reason}, held for a minute; the Ledger's banner reads it.
                   No checks (and ok) when the server runs with no config to check
GET /api/machines[?open=NAME][&before=T][&limit=N]
                   {open, machines, more}: the next `limit` machines (default 20, at most 100) entered from the machine
                   `open` (default the In Progress machine), newest activity first, each whole as a snapshot `flows`
                   entry with its derivation. `before` is the `last` of the last machine held (epoch seconds; none:
                   the newest; a machine with no task counts as 0), machines sharing the boundary activity all come in
                   one page, so walking `before` neither repeats nor skips one. An `open` that is not a machine here is
                   404, a `before` that is not a finite number or a `limit` outside 1-100 is 400
GET /api/history?task=TASK-N[&flow=NAME]
                   {task, path}: the task's Board lane changes as [{at, from, to}], oldest first (`at`
                   epoch seconds). With `flow`, {task, flow, path, steps}: its events on that lifecycle
                   machine as [{at, event, state}] in order, `steps` their count. A task never seen has an empty path; no `task` is 400
                   and an unknown `flow` 404. The machine events are copied from their stream as they
                   arrive into the history database (`database_url`, else starpulse-history.sqlite beside
                   the config), so the path outlives the stream's trim, unless the board adapter keeps
                   its own history. A trim past entries the copy never read is recorded as a gap
GET /api/analytics/health[?hours=N][&stuck_hours=N]
                   the Board's flow health from the history's lane changes (`analytics.board_health`): `states`
                   (each with `wip` now and, for a state that is not final, the `visits`, `mean_s` and `max_s` of
                   its stays over the last `hours`, default 168, `open` of them still going and counted to now),
                   `throughput` {count, per_day} into a final state, `stuck` (tasks in a middle state for
                   `stuck_hours` or longer, default 24, each `counted_to_now`) and `warnings` (the history's
                   recorded gaps). A `hours` or `stuck_hours` that is no positive number is 400; a history that
                   does not keep lane changes for every task is 501
GET /api/analytics/sessions[?hours=N]
                   session and slice health from the harness OTLP exports the Claude Code receiver recorded
                   (`sessions.session_health`, `sessions.slice_health`) over the last `hours`, default 168:
                   `sessions` (one row per harness session and task, with its prompts, requests, tools,
                   rejections, tokens, cost and agent, operator-wait and idle seconds) and `slices` (per task, the
                   sessions that worked it with its interventions, `escalated` and `clean`). A `hours` that is no
                   positive number is 400, a server with no telemetry log 501 and one that cannot read it 503
GET /api/level[?hours=N]
                   the level's flow numbers on the Backlog flow metric definitions (`level_metrics`), over the
                   last `hours`, default 168: `wip`, `throughput`, `time_in_state`, `aging`, and the orbit's
                   `terminals` and `working` totals, plus per source (the forwarder an event id names) its
                   `ended` runs with `terminal_share` and its `dwell` with `time_share`, each set summing to 1, and
                   whether it is `shared` (a forwarder named it). `level` echoes the config the orbit card draws
                   (title, subject, runs, gates, terminals with roles, orbit, facets, activity) and `arrivals` lists
                   each entry into a terminal inside the window, `{source, state, at}` oldest first, for the comets.
                   A `hours` that is no positive number is 400, as is one longer than the history, with
                   `history_s` its length; a server with no `[level]` table or not serving `--hub` is 404, and a
                   history that does not keep runs is 501
GET /api/level/trajectories[?hours=N]
                   the trajectory analytics (`trajectories.trajectory_analytics`) of the level's runs that ended in a
                   terminal in the last `hours`, default 168: `variants` and the `norm`, `outliers` ranked by
                   Levenshtein distance from it, the absorbing `chain` (expected days and `p_goal` per state),
                   `betweenness` and the path-time `bottleneck`, the rework `loops` (each back-edge with its runs,
                   trips and days), per configured gate whether it is `bypassable` with the bypassing run's
                   `witness` path, and per run its `back_edges`, `sccs`, `loops` and own `gates` with their
                   `dominators` and `post_dominators`, computed on that run's graph and never the union of all
                   runs'; the `forecast` of each run still going (its chance of each terminal and of the goal and
                   its expected days, from its state's row conditioned on its loops so far, with the row's sample
                   size `n` and whether it is `pooled`), and the `calibration` of that forecast per decile on the
                   latest fifth of the ended runs. The window and its refusals are `/api/level`'s
GET /api/level/what-if?from=STATE&to=STATE&p=P[&hours=N]
                   the chain of `/api/level/trajectories` with `from -> to` at probability `p`, `from`'s other exits
                   keeping their shares of the rest (`trajectories.what_if`): `p_goal` and `expected_days` from the
                   usual first state `start`, each `{before, after, change}`, and the changed `chain`. 400 for a
                   missing or unparsed parameter, a state no ended run left, a `p` outside 0 to 1, no other exit,
                   or a chain that never finishes; the window and its other refusals are `/api/level`'s
GET /api/harnesses  {tiers, harnesses} from the config's `harnesses_file`; both empty with no file
POST /api/runs/events
                   push one run event from a producer that cannot reach the event log, with `Authorization: Bearer
                   <token>`: {phase, workflow: "<instance>/<workflow>", run_id, status[, time, step, depends]}, the
                   fields of `starpulse emit`. Each `[[runs]]` instance with a `token_env` has its own token, read from
                   that environment variable at start, and a token pushes only its own instance's workflows. 201
                   {accepted} when the log took the event, which the page draws as `pushed/<instance>/<workflow>`;
                   401 for a missing or wrong token, 403 for another instance's workflow, 400 for an event the contract
                   does not allow, 413 over 64 KiB, 503 when the log refuses it, 404 when no instance has a token. A
                   refusal writes nothing. A GET answers 405
POST /api/insights
                   a hub's fourth contract (`serve --hub` with `engine_token_env` in `[oidc]`; any other server answers
                   404): an external engine posts one `Finding` {id, engine {name, version}, scope {team, machine,
                   state, task}, severity (info, warn, act), text (at most 280 characters), evidence [{label, url or
                   query}], created_at[, expires_at]} with `Authorization: Bearer <engine token>`, which no viewer's
                   session or forwarder's token replaces. 201 {id, replaced: false}; 200 {id, replaced: true} when a
                   re-post of the id replaced a finding that was not retracted; 400 naming the field to fix, and a
                   `scope` that names a person is one, since the contract has no person field; 413 over 64 KiB; 503
                   when the history store refuses it. A refusal writes and sends nothing. The finding is kept in the
                   history's `starpulse_insights` table, and `/api/events` sends an `insight` event {id, finding}, whose
                   snapshot lists the live `insights`. A GET answers 405
DELETE /api/insights/<id>
                   retract a finding with the engine token: 200 {id, retracted: true}, and an `insight` event {id,
                   finding: null}; 404 for an id that is unknown or already retracted. The row stays in the history
"""

from __future__ import annotations

import argparse
import functools
import gzip
import io
import json
import logging
import math
import os
import queue
import shutil
import signal
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Collection, Mapping
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from starpulse._internal.board.seam import (
    AssigneeWriter,
    Board,
    MoveWriter,
    TaskArchiver,
    TaskCreator,
    TaskEditor,
    TaskReader,
    Written,
)
from starpulse._internal.board.seam import load as load_board
from starpulse._internal.harnesses.harness import HARNESS_MACHINES
from starpulse._internal.harnesses.session_start import starter
from starpulse._internal.runs import run_events
from starpulse._internal.runs.ingest import MAX_BODY, MAX_FORWARD_BODY, ForwardIngest, Ingest
from starpulse._internal.runs.ingest import tokens as ingest_tokens
from starpulse._internal.pulls.release import READY, RELEASE_S, Releaser
from starpulse._internal.config.pins import GitHub
from starpulse._internal.pulls.pull_requests import PullRequests
from starpulse._internal.pulls.pull_store import PullSync
from starpulse._internal.runs.push_runs import PUSHED_INSTANCE, PushRuns
from starpulse._internal.runs.triggers import run_triggers
from starpulse._internal.hub import forward
from starpulse._internal.server.compression import LEVEL, Encoded, accepts_gzip, compressed, gzip_stream
from starpulse._internal.hub.forward import Forwarder
from starpulse._internal.feed.snapshot_cache import KEPT, SnapshotCache
from starpulse._internal.server.writes import (
    autopilot,
    OPERATOR,
    archive_doc,
    archive_milestone,
    archive_task,
    create_doc,
    create_milestone,
    create_task,
    doc_record,
    docs_list,
    edit_doc,
    edit_milestone,
    edit_task,
    forwarding,
    history_window,
    milestone_record,
    milestones_list,
    move_task,
    reconcile_lanes,
    rerun_dag,
    run_dag,
    start_task,
    task_record,
    write_refusal,
)
from starpulse.contracts.api import encode, event
from starpulse._internal.config.level import Level
from starpulse._internal.eventlog.level_metrics import RunWindow, WindowPastHistory, level_metrics
from starpulse._internal.machines.snapshot import qualifier
from starpulse._internal.level.trajectories import WhatIfRefused, trajectory_analytics, what_if
from starpulse._internal.level import analytics
from starpulse._internal.level.sessions import session_health, slice_health
from starpulse.contracts.adapters import TaskKeys
from starpulse._internal.cli import doctor
from starpulse._internal.feed.board_feed import WAITING, BoardFeed, follow
from starpulse._internal.ci.ci import attach
from starpulse._internal.ci.ci_trail import CiTrail
from starpulse._internal.level.insights import Insights, InsightStore, restore
from starpulse._internal.feed.ledger import PAGE
from starpulse._internal.feed.machine_tasks import MachineTasks
from starpulse._internal.feed.machine_tasks import tables as machine_tables
from starpulse._internal.config.config import Config, ConfigError, RunsInstance, discover, load, runs_adapter
from starpulse._internal.config.harnesses import Harnesses
from starpulse._internal.autopilot.runtime import Runtime, build as build_autopilot
from starpulse._internal.autopilot.starter import builtin_starter
from starpulse._internal.autopilot.toggle import TOGGLE_FILE
from starpulse._internal.config.history_window import SETTINGS_FILE, HistoryWindow
from starpulse._internal.eventlog import events as machine_events
from starpulse._internal.eventlog import lane_events
from starpulse._internal.eventlog.event_log import EventLog, prune_forever
from starpulse._internal.eventlog.history import (
    HealthHistory,
    History,
    HistoryStore,
    LevelHistory,
    SummarisedHealth,
    SummarisedLevel,
    database_url,
    record_lane_events,
    record_machine_events,
)
from starpulse._internal.pulls.pulls import PullStore
from starpulse._internal.harnesses.telemetry import TelemetryLog

logger = logging.getLogger(__name__)
_HERE = Path(__file__).parents[2]
#: The Vite build of web/; it holds nothing but the page, so all of it is served.
_STATIC = _HERE / "static"
#: The page's one address and the retired per-graph ones, which the page redirects to their level.
_PAGES = {"/", "/board", "/runs"}
#: Seconds an idle event stream waits before a keep-alive comment, which is how a closed page is noticed.
_PING_S = 15.0
_RUN = "/api/run/"
_RERUN = "/api/runs/"
_RERUN_TAIL = "/rerun"
_MOVE = "/api/move"
_START = "/api/start"
_WINDOW = "/api/history-window"
_FORWARDING = "/api/forwarding"
_AUTOPILOT = "/api/autopilot"
_TASK = "/api/task/"
_SNAPSHOT_BODY = "/api/events/body/"
_EDIT = "/api/edit"
_ARCHIVE = "/api/archive"
_TASKS = "/api/tasks"
_MILESTONES = "/api/milestones"
_MILESTONE_EDIT = "/api/milestones/edit"
_MILESTONE_ARCHIVE = "/api/milestones/archive"
_DOCS = "/api/docs"
_DOC_EDIT = "/api/docs/edit"
_DOC_ARCHIVE = "/api/docs/archive"
_INGEST = "/api/runs/events"
_FORWARD = "/api/forward"
_INSIGHTS = "/api/insights"
#: The write routes of milestone records; `/api/milestones/<id>` reads one, so a GET of these answers 405.
_MILESTONE_WRITES = frozenset({_MILESTONES, _MILESTONE_EDIT, _MILESTONE_ARCHIVE})
#: The write routes of doc records; `/api/docs/<id>` reads one, so a GET of these answers 405.
_DOC_WRITES = frozenset({_DOCS, _DOC_EDIT, _DOC_ARCHIVE})
#: The body each write route answers, by `contracts.api.BODIES`; a run and a rerun answer `run`.
_WRITES = {
    _MOVE: "move",
    _START: "start",
    _EDIT: "edit",
    _ARCHIVE: "archive",
    _TASKS: "create",
    _MILESTONES: "milestone_create",
    _MILESTONE_EDIT: "milestone_edit",
    _MILESTONE_ARCHIVE: "milestone_archive",
    _DOCS: "doc_create",
    _DOC_EDIT: "doc_edit",
    _DOC_ARCHIVE: "doc_archive",
    _INGEST: "ingest",
    _FORWARD: "forward",
    _INSIGHTS: "insight",
}
#: The most rows `/api/merges` and `/api/machines` serve at once.
_PAGE_LIMIT = 100


def _is_rerun(path: str) -> bool:
    """Whether `path` is `/api/runs/<instance>/<workflow>/rerun`; the ingest route `/api/runs/events` is not."""
    return path.startswith(_RERUN) and path.endswith(_RERUN_TAIL) and path.count("/") == 5


def _error(message: str) -> bytes:
    return encode("error", {"error": message})


def _page_query(query: dict[str, list[str]], noun: str) -> tuple[float | None, int] | bytes:
    """The `before` and `limit` of a paged route, or the 400 body for one that is malformed."""
    try:
        before = float(query["before"][0]) if "before" in query else None
        limit = int(query["limit"][0]) if "limit" in query else PAGE
    except ValueError:
        return _error(f"{noun} takes a numeric ?before= and an integer ?limit=")
    if before is not None and not math.isfinite(before) or not 0 < limit <= _PAGE_LIMIT:
        return _error(f"{noun} takes a finite ?before= and a ?limit= from 1 to {_PAGE_LIMIT}")
    return before, limit


def merges_response(feed: BoardFeed, query: dict[str, list[str]]) -> tuple[bytes, int]:
    """The body and status for `/api/merges`: the merge ledger's next page, older than `before`, at most `limit` long."""
    asked = _page_query(query, "merges")
    if isinstance(asked, bytes):
        return asked, 400
    return encode("merges", feed.merges(*asked)), 200


def machines_response(feed: BoardFeed, query: dict[str, list[str]]) -> tuple[bytes, int]:
    """The body and status for `/api/machines`: the next page of machines entered from `open`, older than `before`."""
    asked = _page_query(query, "machines")
    if isinstance(asked, bytes):
        return asked, 400
    open_ = query["open"][0] if "open" in query else None
    found = feed.machine_rows(open_, *asked)
    if found is None:
        return _error(f"{open_} is not a machine here"), 404
    return encode("machines", found), 200


def history_response(history: History, query: dict[str, list[str]], flows: Collection[str]) -> tuple[bytes, int]:
    """The body and status for `/api/history`: a task's lane path, or with `flow` its path on that machine.

    `flows` are the machines the page draws."""
    task, flow = (query.get(key, [""])[0] for key in ("task", "flow"))
    if not task:
        return _error("history needs ?task=TASK-N"), 400
    if flow and flow not in flows:
        return _error(f"unknown flow {flow}"), 404
    body: dict[str, Any] = {"task": task}
    if flow:
        body |= {"flow": flow}
        body["path"], body["steps"] = history.machine_path(task, flow)
    else:
        body["path"] = history.lane_path(task)
    return encode("history", body), 200


def pulls_response(pulls: PullStore | None, query: dict[str, list[str]]) -> tuple[bytes, int]:
    """The body and status for `/api/pulls`: the stored pull requests matching every filter given.

    A `number` that is not an integer, or a `state` that is not open, merged or closed, is 400."""
    state = query.get("state", [""])[0].upper() or None
    try:
        number = int(query["number"][0]) if "number" in query else None
    except ValueError:
        return _error("pulls takes an integer ?number="), 400
    if state not in (None, "OPEN", "MERGED", "CLOSED"):
        return _error("pulls takes ?state= open, merged or closed"), 400
    found = (
        pulls.find(query.get("repo", [""])[0] or None, number, state, query.get("body_contains", [""])[0] or None)
        if pulls
        else []
    )
    return encode("pulls", {"pulls": found}), 200


#: `/api/analytics/health`'s defaults: the window it counts over, and how long a stay in one state makes a task stuck.
_HEALTH_HOURS = 168.0
_STUCK_HOURS = 24.0


def _hours(query: dict[str, list[str]], key: str, default: float) -> float | None:
    """The positive, finite number of hours `key` gives, `default` when absent; None for anything else."""
    try:
        hours = float(query[key][0]) if key in query else default
    except ValueError:
        return None
    return hours if 0 < hours < float("inf") else None


def health_response(
    history: History, query: dict[str, list[str]], machines: Mapping[str, dict], now: float
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/health`: the Board's flow health over the last `hours` as of `now`."""
    window = _hours(query, "hours", _HEALTH_HOURS)
    stuck = _hours(query, "stuck_hours", _STUCK_HOURS)
    if window is None or stuck is None:
        return _error("hours and stuck_hours must each be a positive number"), 400
    if not isinstance(history, HealthHistory):
        return _error("this history does not keep every task's lane changes, so it cannot report flow health"), 501
    start = now - window * 3600
    if isinstance(history, SummarisedHealth):
        held = history.health_stays(machines["board"], start=start, now=now, stuck_s=stuck * 3600)
    else:
        held = analytics.lane_stays(history.lane_rows(), start=start, now=now, stuck_s=stuck * 3600)
    health = analytics.stay_health(
        machines["board"], held, history.gaps(), now=now, window_s=window * 3600, stuck_s=stuck * 3600
    )
    return encode("health", health), 200


def sessions_response(
    telemetry: TelemetryLog | None, query: dict[str, list[str]], keys: TaskKeys | None, now: float
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/sessions`: session and slice health of the signals from the last
    `hours` (default 168) as of `now`. An instance that receives no harness telemetry is 501, a log that cannot be
    read 503."""
    window = _hours(query, "hours", _HEALTH_HOURS)
    if window is None:
        return _error("hours must be a positive number"), 400
    if telemetry is None:
        return _error("this instance receives no harness telemetry, so it cannot report session health"), 501
    try:
        found = telemetry.read(now - window * 3600)
    except Exception as exc:  # the event log's database is unreachable
        logger.warning("sessions: telemetry unreadable: %s", exc)
        return _error("the telemetry log cannot be read"), 503
    rows = session_health(found, keys)
    body = {"now": now, "window_s": window * 3600, "sessions": rows, "slices": slice_health(rows)}
    return encode("sessions", body), 200


def level_response(
    history: History, query: dict[str, list[str]], level: Level | None, machines: Mapping[str, dict], now: float
) -> tuple[bytes, int]:
    """The body and status for `/api/level`: the level's flow numbers over the last `hours` as of `now`.

    A window longer than the history is 400 with the history's length (`history_s`), never answered with its missing
    days as zero; a server with no level is 404."""
    return _level_view("level", history, query, level, machines, now, level_metrics)


def trajectories_response(
    history: History, query: dict[str, list[str]], level: Level | None, machines: Mapping[str, dict], now: float
) -> tuple[bytes, int]:
    """The body and status for `/api/level/trajectories`: the trajectory analytics of the runs that ended in the last
    `hours` as of `now`, refused as `level_response` refuses a window."""
    return _level_view("trajectories", history, query, level, machines, now, trajectory_analytics)


def what_if_response(
    history: History, query: dict[str, list[str]], level: Level | None, machines: Mapping[str, dict], now: float
) -> tuple[bytes, int]:
    """The body and status for `/api/level/what-if`: the trajectories' chain with `from -> to` at probability `p`,
    refused as `level_response` refuses a window and with 400 for a what-if the chain cannot answer."""
    origin, to, p = (query.get(key, [""])[0] for key in ("from", "to", "p"))
    try:
        chance = float(p)
    except ValueError:
        chance = None
    if not origin or not to or chance is None:
        return _error("what-if needs ?from=STATE&to=STATE&p=P"), 400
    view = functools.partial(what_if, origin=origin, to=to, p=chance)
    try:
        return _level_view("what_if", history, query, level, machines, now, view)
    except WhatIfRefused as exc:
        return _error(str(exc)), 400


def _level_view(
    kind: str,
    history: History,
    query: dict[str, list[str]],
    level: Level | None,
    machines: Mapping[str, dict],
    now: float,
    view: Callable[..., dict[str, Any]],
) -> tuple[bytes, int]:
    if level is None:
        return _error("this server has no level: add a [level] table and serve with --hub"), 404
    window = _hours(query, "hours", _HEALTH_HOURS)
    if window is None:
        return _error("hours must be a positive number"), 400
    if not isinstance(history, LevelHistory):
        return _error("this history does not keep every task's trajectory, so it cannot report the level"), 501
    try:
        if isinstance(history, SummarisedLevel):
            held = history.level_window(level, now=now, window_s=window * 3600)
        else:
            held = RunWindow(history.level_runs(level.machine))
        answer = view(
            level,
            machines[level.machine],
            held.runs,
            now=now,
            window_s=window * 3600,
            history_start=held.first,
            sources=held.sources,
        )
    except WindowPastHistory as exc:
        return encode(kind, {"error": str(exc), "history_s": exc.history_s}), 400
    return encode(kind, answer), 200


#: The Vite build names every file under it by its content's digest, so a new build never reuses a name.
_ASSETS = "/assets/"
_KEPT = "public, max-age=31536000, immutable"
#: The static files worth gzipping: the build's text. Its images and fonts are already compressed.
_TEXT = (".html", ".js", ".mjs", ".css", ".svg", ".json", ".map")


@functools.lru_cache(maxsize=64)
def _gzipped(path: str, mtime_ns: int) -> bytes:
    """A static file gzipped once per build: `mtime_ns` keys a rebuilt file afresh."""
    return gzip.compress(Path(path).read_bytes(), compresslevel=LEVEL, mtime=0)


class _ApiHandler(SimpleHTTPRequestHandler):
    """The run endpoint and the JSON answer every API route sends; the page's routes subclass it."""

    #: The page's scripts are `text/javascript` on every host: the host's MIME table may call them `application/javascript`.
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".mjs": "text/javascript"}

    starts: Mapping[str, Callable[[str], str]]
    reruns: Mapping[str, Callable[[str, Mapping[str, str]], str]]
    run_safe: Collection[str]
    feed: BoardFeed
    window: HistoryWindow
    writer: MoveWriter
    assign: AssigneeWriter
    start_session: Callable[[str], str] | None
    read: TaskReader | None
    edit: TaskEditor | None
    archive: TaskArchiver | None
    create: TaskCreator | None
    ingest: Ingest | None
    insights: Insights | None
    gate: Callable[[BaseHTTPRequestHandler], bool] | None
    forward: ForwardIngest | None
    forwarding: Forwarder | None
    autopilot: Runtime | None
    milestones: Board | None

    #: Whether the response being written is a hashed build asset's file, which a browser may keep for good.
    _immutable = False

    def send_head(self) -> Any:
        """A static file's headers and the file to copy, gzipped when it is text and the page accepts gzip."""
        path = self.translate_path(self.path)
        self._immutable = urlsplit(self.path).path.startswith(_ASSETS) and os.path.isfile(path)
        if not (path.endswith(_TEXT) and os.path.isfile(path) and accepts_gzip(self.headers.get("Accept-Encoding"))):
            return super().send_head()
        body = _gzipped(path, os.stat(path).st_mtime_ns)
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(path))  # pragma: no mutate: names are case-insensitive
        self.send_header("Content-Encoding", "gzip")  # pragma: no mutate: names are case-insensitive
        self.send_header("Vary", "Accept-Encoding")  # pragma: no mutate: names are case-insensitive
        self.send_header("Content-Length", str(len(body)))  # pragma: no mutate: names are case-insensitive
        self.end_headers()
        return io.BytesIO(body)

    def end_headers(self) -> None:
        if self._immutable:
            self.send_header("Cache-Control", _KEPT)  # pragma: no mutate: names are case-insensitive
            self._immutable = False
        super().end_headers()

    def handle_one_request(self) -> None:
        """Answer the request; a body its model refuses is a logged 500, since the page reads only what a model names."""
        try:
            super().handle_one_request()
        except ValidationError:
            logger.exception("StarPulse: %s %s built a body its model refuses", self.command, self.path)
            self._send(encode("error", {"error": "the server built a body its contract refuses"}), 500)

    def parse_request(self) -> bool:
        """Parse the request, then let the gate (a hub's sign-in) answer or admit it before any route sees it."""
        return super().parse_request() and (self.gate is None or self.gate(self))

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if (
            path.startswith(_RUN)
            or _is_rerun(path)
            or path
            in {_MOVE, _START, _EDIT, _ARCHIVE, _TASKS, _INGEST, _FORWARD, _INSIGHTS, *_MILESTONE_WRITES, *_DOC_WRITES}
        ):
            self.send_response(405)
            self.send_header("Allow", "POST")  # pragma: no mutate: names are case-insensitive
            self.end_headers()
        else:
            super().do_GET()

    def _refused_write(self) -> bool:
        """Answer a write another web page may have sent with its refusal; whether it did."""
        headers = self.headers
        if (refusal := write_refusal(headers.get("Origin"), headers.get("Host"), headers.get("Content-Type"))) is None:
            return False
        self._send(encode("error", refusal[1]), refusal[0])
        return True

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if (
            path in {_MOVE, _START, _EDIT, _ARCHIVE, _TASKS, *_MILESTONE_WRITES, *_DOC_WRITES}
            or path.startswith(_RUN)
            or _is_rerun(path)
        ) and self._refused_write():
            return
        kind = _WRITES.get(path, "run")
        if path in {_MOVE, _START, _EDIT, _ARCHIVE, _TASKS, *_MILESTONE_WRITES, *_DOC_WRITES}:
            declared = self.headers.get("Content-Length")  # pragma: no mutate: header names are case-insensitive
            raw = self.rfile.read(int(declared or 0))
            if path == _MOVE:
                status, body = move_task(self.client_address[0], raw, self.feed, self.writer)
            elif path == _EDIT:
                status, body = edit_task(self.client_address[0], raw, self.feed, self.read, self.edit)
            elif path == _ARCHIVE:
                status, body = archive_task(self.client_address[0], raw, self.feed, self.archive)
            elif path == _TASKS:
                status, body = create_task(self.client_address[0], raw, self.create)
            elif path == _MILESTONES:
                status, body = create_milestone(self.client_address[0], raw, self.milestones)
            elif path == _MILESTONE_EDIT:
                status, body = edit_milestone(self.client_address[0], raw, self.milestones)
            elif path == _MILESTONE_ARCHIVE:
                status, body = archive_milestone(self.client_address[0], raw, self.milestones)
            elif path == _DOCS:
                status, body = create_doc(self.client_address[0], raw, self.milestones)
            elif path == _DOC_EDIT:
                status, body = edit_doc(self.client_address[0], raw, self.milestones)
            elif path == _DOC_ARCHIVE:
                status, body = archive_doc(self.client_address[0], raw, self.milestones)
            else:
                status, body = start_task(self.client_address[0], raw, self.feed, self.assign, self.start_session)
        elif path == _INGEST and self.ingest is not None:
            status, body = self._pushed(self.ingest, MAX_BODY)
        elif path == _FORWARD and self.forward is not None:
            status, body = self._pushed(self.forward, MAX_FORWARD_BODY)
        elif path == _INSIGHTS and self.insights is not None:
            status, body = self._pushed(self.insights, MAX_BODY)
        elif _is_rerun(path):
            name = unquote(path.removeprefix(_RERUN).removesuffix(_RERUN_TAIL))
            status, body = rerun_dag(self.client_address[0], name, self.feed, self.reruns, self.run_safe)
        elif path.startswith(_RUN):
            status, body = run_dag(self.client_address[0], unquote(path.removeprefix(_RUN)), self.starts, self.run_safe)
        else:
            self.send_error(404)
            return
        self._send(encode(kind, body), status)

    def _pushed(self, ingest: Callable[[str | None, bytes], tuple[int, dict]], limit: int) -> tuple[int, dict]:
        """Answer one token-guarded push; a body over `limit` is refused unread and the connection closed."""
        try:
            declared = int(self.headers.get("Content-Length") or 0)  # pragma: no mutate: case-insensitive
        except ValueError:
            declared = 0
        if declared > limit:
            self.close_connection = True  # the body was not read, so the connection cannot carry another request
            return 413, {"error": f"a body is at most {limit} bytes"}
        return ingest(self.headers.get("Authorization"), self.rfile.read(max(declared, 0)))

    def do_PUT(self) -> None:
        self._window("PUT")

    def do_DELETE(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith(f"{_INSIGHTS}/") and self.insights is not None:
            status, body = self.insights.retract(unquote(path.removeprefix(f"{_INSIGHTS}/")))
            self._send(encode("insight", body), status)
        else:
            self._window("DELETE")

    def _window(self, method: str) -> None:
        """Answer the route a PUT or DELETE names: the history window's, or a PUT to the forwarding opt-in or the autopilot switch."""
        path = urlsplit(self.path).path
        if path == _AUTOPILOT and method == "PUT":
            if self._refused_write():
                return
            declared = self.headers.get("Content-Length")  # pragma: no mutate: header names are case-insensitive
            self._send(*self._autopilot(method, self.rfile.read(int(declared or 0))))
            return
        if path == _FORWARDING and method == "PUT":
            if self._refused_write():
                return
            declared = self.headers.get("Content-Length")  # pragma: no mutate: header names are case-insensitive
            self._send(*self._forwarding(method, self.rfile.read(int(declared or 0))))
            return
        if path != _WINDOW:
            self.send_error(404)
            return
        if method != "GET" and self._refused_write():
            return
        declared = self.headers.get("Content-Length")  # pragma: no mutate: header names are case-insensitive
        status, body = history_window(self.client_address[0], method, self.rfile.read(int(declared or 0)), self.window)
        self._send(encode("window", body), status)

    def _autopilot(self, method: str, raw: bytes) -> tuple[bytes, int]:
        status, body = autopilot(self.client_address[0], method, raw, self.autopilot)
        return encode("autopilot", body), status

    def _forwarding(self, method: str, raw: bytes) -> tuple[bytes, int]:
        status, body = forwarding(self.client_address[0], method, raw, self.forwarding)
        return encode("forwarding", body), status

    def _send(
        self, body: bytes | Encoded, status: int = 200, cache: str = "no-store", content_type: str = "application/json"
    ) -> None:
        """`body` as JSON unless told otherwise; an `Encoded` one is sent as the gzip it already holds to a page that
        accepts gzip."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", cache)
        accepted = self.headers.get("Accept-Encoding")
        if isinstance(body, Encoded):
            body, gzipped = body.body, body.gzipped if accepts_gzip(accepted) else None
        else:
            gzipped = compressed(body, accepted)
        if gzipped is not None:
            body = gzipped
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)


def _no_writer(task: str, status: str, actor: str = OPERATOR) -> Written:
    return Written(False, "no board writer is configured", unavailable=True)


#: How long `/api/doctor` holds its report: the checks read the scheduler and run `git`.
_CONTRACT_TTL_S = 60


def _cached(
    read: Callable[[], dict[str, Any]], ttl: float, clock: Callable[[], float] = time.monotonic
) -> Callable[[], dict[str, Any]]:
    """`read`, asked at most once in `ttl` seconds; the page that asks while it is stale waits for the fresh read."""
    held: tuple[float, dict[str, Any]] | None = None
    lock = threading.Lock()

    def get() -> dict[str, Any]:
        nonlocal held
        with lock:
            if held is None or clock() - held[0] >= ttl:
                held = (clock(), read())
            return held[1]

    return get


def request_handler(
    feed: BoardFeed,
    static: Path,
    starts: Mapping[str, Callable[[str], str]],
    run_safe: Collection[str],
    history: History,
    window: HistoryWindow,
    writer: MoveWriter = _no_writer,
    harnesses: Harnesses | None = None,
    assign: AssigneeWriter = _no_writer,
    start_session: Callable[[str], str] | None = None,
    read: TaskReader | None = None,
    edit: TaskEditor | None = None,
    archive: TaskArchiver | None = None,
    create: TaskCreator | None = None,
    clock: Callable[[], float] = time.time,
    ingest: Ingest | None = None,
    gate: Callable[[BaseHTTPRequestHandler], bool] | None = None,
    forward: ForwardIngest | None = None,
    level: Level | None = None,
    insights: Insights | None = None,
    forwarding: Forwarder | None = None,
    autopilot: Runtime | None = None,
    reruns: Mapping[str, Callable[[str, Mapping[str, str]], str]] | None = None,
    contract: Callable[[], dict[str, Any]] | None = None,
    milestones: Board | None = None,
    pulls: PullStore | None = None,
    telemetry: TelemetryLog | None = None,
) -> type[SimpleHTTPRequestHandler]:
    harnesses_body = encode("harnesses", (harnesses or Harnesses((), {})).as_json())
    snapshots = SnapshotCache(feed)
    pull_reads = _PullReads(pulls)
    snapshot_bodies = _SnapshotBodies()
    event_text = _EventText()
    flows = feed.machines.keys()

    class Handler(_ApiHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.starts = starts  # set first: the base __init__ handles the request
            self.reruns = reruns or {}
            self.run_safe = run_safe
            self.feed = feed
            self.window = window
            self.writer = writer
            self.assign = assign
            self.start_session = start_session
            self.read = read
            self.edit = edit
            self.archive = archive
            self.create = create
            self.ingest = ingest
            self.insights = insights
            self.gate = gate
            self.forward = forward
            self.forwarding = forwarding
            self.autopilot = autopilot
            self.milestones = milestones
            super().__init__(*args, directory=str(static), **kwargs)  # pragma: no mutate: the server passes no kwargs

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            if url.path == "/api/events":
                self._stream_events(parse_qs(url.query).get("snapshot") == ["ref"])
            elif url.path.startswith(_SNAPSHOT_BODY):
                self._snapshot_body(url.path.removeprefix(_SNAPSHOT_BODY))
            elif url.path == "/api/snapshot":
                served = snapshots.get()
                self._send(snapshot_bodies(served.key, served.body))
            elif url.path == "/api/merges":
                self._send(*merges_response(feed, parse_qs(url.query)))
            elif url.path == "/api/doctor":
                self._send(encode("doctor", contract() if contract else {"ok": True, "checks": []}))
            elif url.path == "/api/machines":
                self._send(*machines_response(feed, parse_qs(url.query)))
            elif url.path == "/api/history":
                self._send(*history_response(history, parse_qs(url.query), flows))
            elif url.path == "/api/pulls":
                self._send(*pull_reads(url.query))
            elif url.path == "/metrics":
                self._send(
                    (pulls.age_gauge(clock()) if pulls else "").encode(),
                    content_type="text/plain; version=0.0.4; charset=utf-8",
                )
            elif url.path == "/api/analytics/health":
                self._send(*health_response(history, parse_qs(url.query), feed.machines, clock()))
            elif url.path == "/api/analytics/sessions":
                self._send(*sessions_response(telemetry, parse_qs(url.query), feed.keys, clock()))
            elif url.path == "/api/level":
                self._send(*level_response(history, parse_qs(url.query), level, feed.machines, clock()))
            elif url.path == "/api/level/trajectories":
                self._send(*trajectories_response(history, parse_qs(url.query), level, feed.machines, clock()))
            elif url.path == "/api/level/what-if":
                self._send(*what_if_response(history, parse_qs(url.query), level, feed.machines, clock()))
            elif url.path.startswith(_TASK):
                status, body = task_record(feed, read, unquote(url.path.removeprefix(_TASK)))
                self._send(encode("task", body), status)
            elif url.path == _MILESTONES:
                status, body = milestones_list(self.milestones)
                self._send(encode("milestones", body), status)
            elif url.path.startswith(f"{_MILESTONES}/") and url.path not in _MILESTONE_WRITES:
                status, body = milestone_record(self.milestones, unquote(url.path.removeprefix(f"{_MILESTONES}/")))
                self._send(encode("milestone", body), status)
            elif url.path == _DOCS:
                status, body = docs_list(self.milestones)
                self._send(encode("docs", body), status)
            elif url.path.startswith(f"{_DOCS}/") and url.path not in _DOC_WRITES:
                status, body = doc_record(self.milestones, unquote(url.path.removeprefix(f"{_DOCS}/")))
                self._send(encode("doc", body), status)
            elif url.path == "/api/harnesses":
                self._send(harnesses_body)
            elif url.path == _WINDOW:
                self._window("GET")  # pragma: no mutate: any method but PUT and DELETE reads the window
            elif url.path == _FORWARDING:
                self._send(*self._forwarding("GET", b""))
            elif url.path == _AUTOPILOT:
                self._send(*self._autopilot("GET", b""))
            elif url.path in _PAGES or url.path.startswith("/flow/") and url.path[6:] in flows - {"board"}:
                self.path = "/index.html"
                super().do_GET()
            else:
                super().do_GET()

        def list_directory(self, path: str | os.PathLike[str]) -> None:
            self.send_error(404)

        def _snapshot_body(self, key: str) -> None:
            body = snapshots.body(key)
            if body is None:
                return self._send(encode("error", {"error": f"no snapshot {key} is held"}), 404)
            self._send(snapshot_bodies(key, body), cache="max-age=3600, immutable")

        def _stream_events(self, by_ref: bool = False) -> None:
            """Hold the connection open: the Board's snapshot, then each change as it happens. `by_ref` sends the snapshot
            as `ref <path>`, the path its body is read from: a browser reads a long event on its main thread, a fetched
            body off it."""
            changes = None
            try:
                # The held snapshot is sent as it is, however many changes it lacks, so a page connecting while the next
                # one is built is not held up by it: it applies those changes after it.
                served = snapshots.latest() or snapshots.get()
                while (attached := feed.watch_from(served.sent)) is None:
                    served = snapshots.get()
                missed, changes = attached
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")  # pragma: no mutate: names are case-insensitive
                self.send_header("Cache-Control", "no-store")  # pragma: no mutate: names are case-insensitive
                if accepts_gzip(self.headers.get("Accept-Encoding")):
                    self.send_header("Content-Encoding", "gzip")  # pragma: no mutate: names are case-insensitive
                    self._write = gzip_stream(self.wfile)
                else:
                    self._write = self._write_plain
                self.end_headers()
                self._frame("snapshot", f"ref {_SNAPSHOT_BODY}{served.key}" if by_ref else served.body.decode())
                for change in missed:
                    self._event(*change)
                while True:
                    try:
                        self._event(*changes.get(timeout=_PING_S))
                    except queue.Empty:
                        self._write(b": ping\n\n")  # a closed page fails this write, which ends the stream
            except OSError:
                pass
            except ValidationError:
                logger.exception("StarPulse: /api/events sent a body its model refuses; the stream ends")
            finally:
                if changes is not None:
                    feed.unsubscribe(changes)

        def _event(self, name: str, data: dict) -> None:
            self._frame(name, event_text(name, data))

        def _frame(self, name: str, data: str) -> None:
            self._write(f"event: {name}\ndata: {data}\n\n".encode())

        def _write_plain(self, data: bytes) -> None:
            self.wfile.write(data)
            self.wfile.flush()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


def _config(parser: argparse.ArgumentParser, path: Path | None) -> Config:
    """The config in `path`, else `starpulse.toml` beside where the view runs, else the defaults."""
    path = discover(path)
    try:
        return load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")


def _adapter(parser: argparse.ArgumentParser, instance: RunsInstance) -> ModuleType:
    """The runs adapter module of `instance`: `start(url)` gives its start capability or None, `follow(url, sink, log)` reads its workflows from the event log and the instance."""
    try:
        return runs_adapter(instance.type)
    except ConfigError as exc:
        parser.exit(1, f"runs instance {instance.name}: {exc}\n")


def assemble(config: Config, base: Path, window_s: float | None, run_safe: Collection[str]) -> tuple[Board, BoardFeed]:
    """The board the config's `[board]` adapter builds, and the feed that draws it; `base` is the config's directory.

    A task whose latest move on a machine is older than `window_s` seconds (None: never) is not drawn there, and Run
    now is drawn on the `run_safe` workflows.
    """
    board = load_board(config.board_type, config.board, base)
    domains = config.qualified_domains()
    qualify = qualifier(domains)
    drawn = board.machines(qualify, [name for names in domains.values() for name in names])
    # Every harness adapter writes this one machine, so the page draws it unless the board declares a machine of that name.
    machines = {**drawn, **{name: m for name, m in HARNESS_MACHINES.items() if name not in drawn}}
    if config.ci:
        machines = attach(machines, config.ci)
    if config.level:
        config.level.check(machines)
    feed = BoardFeed(
        window_s,
        board.keys,
        config.tracker_url,
        machines=machines,
        domains=domains,
        run_safe=run_safe,
        cues=board.cues(qualify),
        source=board.source,
        capabilities={
            "edit": board.edit is not None,
            "archive": board.archive is not None,
            "create": board.create is not None,
        },
        hint=found_backlog(config, base),
        commit={instance.name: instance.commit for instance in config.runs if instance.commit},
    )
    return board, feed


def found_backlog(config: Config, base: Path) -> str | None:
    """The line that names a Backlog.md project beside `base` and how to switch to it, when the config names no board.

    The default board is StarPulse's own; a project that already has a `backlog/` is told, not adopted. The line ends
    `run: <command>`, which the Connect a tracker modal draws as a copyable block.
    """
    if "type" in config.board or not (project := base / "backlog" / "config.yml").is_file():
        return None
    return (
        f"Found a Backlog.md project at {project}; StarPulse is showing its own board. "
        "To show that project instead, run: starpulse connect backlog --path backlog"
    )


def announce(port: int, hint: str | None) -> None:
    """Say on the terminal where the view is, and the Backlog.md project it found when it did."""
    print(f"StarPulse on :{port}", flush=True)
    if hint:
        print(hint, flush=True)


#: How long the dispatch loop holds the trajectory chain it ranks on: the analytics read the whole history.
_CHAIN_TTL_S = 300


def start_autopilot(
    config: Config,
    base: Path,
    feed: BoardFeed,
    board: Board,
    history: History,
    level: Level | None,
    stop: threading.Event,
    probe: Callable[[], Mapping[str, float]] | None = None,
) -> Runtime:
    """The autopilot's runtime with its sampler and dispatch loop running on daemon threads until `stop` is set.

    The loop admits from the lane `[autopilot] lane` names (else the board's initial lane), starts a session through
    `session_start_url` (else the built-in tmux starter in `base`), and settles a stuck one by moving it to Needs
    attention through the board's editor. Its chain is the trajectory analytics' when this server has a level.
    """

    def settle(task: str, reason: str) -> Written:
        if board.edit is None:
            return Written(False, "this board has no editor", unavailable=True)
        return board.edit(task, {"status": "needs_attention"}, reason)

    def claim(task: str, comment: str) -> Written:
        if board.edit is None:
            return Written(False, "this board has no editor", unavailable=True)
        return board.edit(task, {}, comment)

    def read_chain() -> dict[str, Any]:
        body, status = trajectories_response(history, {}, level, feed.machines, time.time())
        return json.loads(body)["chain"] if status == 200 else {}

    initial = next(state["id"] for state in feed.machines["board"]["states"] if state.get("initial"))
    runtime = build_autopilot(
        config.autopilot,
        base / TOGGLE_FILE,
        feed,
        probe,
        start=starter(config.session_start_url) or builtin_starter(base),
        settle=settle,
        claim=claim,
        chain=_cached(read_chain, _CHAIN_TTL_S),
        lane=config.autopilot.eligible_lane(initial),
    )
    threading.Thread(target=runtime.sampler.run_forever, args=(stop,), name="autopilot-sampler", daemon=True).start()
    if runtime.loop is not None:
        threading.Thread(target=runtime.loop.run_forever, args=(stop,), name="autopilot-loop", daemon=True).start()
    return runtime


def history_store(config: Config, base: Path, machines: Mapping[str, dict]) -> HistoryStore:
    """StarPulse's store at `database_url` or beside the config: the one history `serve` records into and the page reads.

    Opening it puts every StarPulse table, the event log's included, on that database.
    """
    return HistoryStore(database_url(config.database_url, base), machines)


class _SnapshotBodies:
    """Each snapshot body with its gzip, by the key that names it: gzip of the ~1.5 MB snapshot takes tens of ms, so the
    first page to read a snapshot compresses it and the rest are sent that."""

    def __init__(self, keep: int = KEPT) -> None:
        self._keep = keep
        self._held: OrderedDict[str, Encoded] = OrderedDict()
        self._lock = threading.Lock()

    def __call__(self, key: str, body: bytes) -> Encoded:
        with self._lock:
            if (held := self._held.get(key)) is None:
                held = self._held[key] = Encoded.of(body)
                while len(self._held) > self._keep:
                    self._held.popitem(last=False)
            return held


class _PullReads:
    """`/api/pulls`' answers, by query, held until the store saves: the unfiltered list is ~1 MB to read, encode and
    gzip, and every page asks for it."""

    #: How many distinct queries are held; past it the oldest is dropped.
    KEEP = 16

    def __init__(self, pulls: PullStore | None) -> None:
        self._pulls = pulls
        self._held: OrderedDict[str, tuple[int, Encoded, int]] = OrderedDict()
        self._lock = threading.Lock()

    def __call__(self, query: str) -> tuple[Encoded, int]:
        rev = self._pulls.rev if self._pulls else 0
        with self._lock:
            held = self._held.get(query)
        if held is None or held[0] != rev:
            body, status = pulls_response(self._pulls, parse_qs(query))
            held = (rev, Encoded.of(body), status)
            with self._lock:
                self._held[query] = held
                while len(self._held) > self.KEEP:
                    self._held.popitem(last=False)
        return held[1], held[2]


class StarPulseServer(ThreadingHTTPServer):
    """The view's HTTP server, with a listen backlog a crowd of pages connecting at once fits in: the stock 5 drops the
    rest's SYNs, and each waits out a 1 s retransmit before its first byte."""

    request_queue_size = 128


class _EventText:
    """The JSON text of the events last sent, by the data each was made from.

    Every page streaming `/api/events` is handed the same `data` object for a change, and encoding it holds the GIL
    (the `ledgers` event is ~0.7 MB, ~45 ms), so the first page to reach a change encodes it under the lock and the
    others take that text.
    """

    def __init__(self, keep: int = 8) -> None:
        self._keep = keep
        self._lock = threading.Lock()
        self._made: dict[int, tuple[str, Any, str]] = {}

    def __call__(self, name: str, data: Any) -> str:
        with self._lock:
            made = self._made.get(id(data))
            if made is not None and made[0] == name and made[1] is data:
                return made[2]
            text = event(name, data)
            self._made[id(data)] = (name, data, text)  # holds `data`, so its id is not reused while it is here
            while len(self._made) > self._keep:
                del self._made[next(iter(self._made))]
            return text


def serve_until_stopped(server: ThreadingHTTPServer, feed: BoardFeed) -> None:
    """Serve until Ctrl-C or `SIGTERM`, then save the Board the feed keeps, so the next start resumes from it."""
    # a stopped unit leaves through the save below, as Ctrl-C does
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        server.serve_forever()
    finally:
        feed.save()


def serve_parser() -> argparse.ArgumentParser:
    """The `starpulse serve` command line."""
    parser = argparse.ArgumentParser(prog="starpulse serve", description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="the address to listen on; the default answers this machine only, and 0.0.0.0 answers the network",
    )
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--hours",
        type=float,
        default=6.0,
        help="how far back a task's latest move on a machine counts; Admin's override replaces it",
    )
    parser.add_argument("--config", type=Path, help="the TOML config file; default starpulse.toml when it exists")
    parser.add_argument(
        "--hub",
        action="store_true",
        help="serve as a hub: history in the Postgres database_url, its schema migrated to head (needs starpulse[hub])",
    )
    return parser


def keep_event_log(
    log: EventLog, config: Config, base: Path, *, hub: bool, stop: threading.Event
) -> threading.Thread | None:
    """Start the hourly prune of the event log, which archives each row it deletes under `event_log_archive_dir`.

    A hub starts none: it drops a whole day's partition once it has rolled the day up, so its rows are never deleted
    one by one.
    """
    if hub:
        return None
    thread = threading.Thread(
        target=prune_forever,
        args=(log,),
        kwargs={
            "retention_days": config.event_log_retention_days,
            "archive_dir": base / config.event_log_archive_dir,
            "stop": stop,
        },
        name="event-log-prune",
        daemon=True,
    )
    thread.start()
    return thread


def _keep_released(releaser: Releaser, feed: BoardFeed, interval_s: float = RELEASE_S) -> None:  # pragma: no mutate block
    """Once the Board replay is done, release the Waiting tasks whose dependencies settled every `interval_s` seconds;
    a failed pass is logged and never ends the loop."""
    feed.wait_replayed()
    while True:
        try:
            releaser.release()
        except Exception:
            logger.exception("release: the pass failed")
        time.sleep(interval_s)


def main(argv: list[str] | None = None) -> None:  # pragma: no mutate block — serve_forever process boundary
    logging.basicConfig(level=logging.INFO)  # the GraphQL cost of each pull request read is an INFO line
    parser = serve_parser()
    args = parser.parse_args(argv)
    config = _config(parser, args.config)
    try:
        instance_tokens = ingest_tokens(config.runs, os.environ)
        source_tokens = ingest_tokens(config.sources, os.environ)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    gate = None
    if args.hub:
        try:
            from starpulse._internal.hub import (
                hub,  # noqa: PLC0415 - hub-only code; an IC instance never imports it
                oidc,  # noqa: PLC0415 - hub-only code; an IC instance never imports it
            )
        except ImportError as exc:
            parser.exit(1, f"hub mode needs the hub extras: pip install 'starpulse[hub]' ({exc})\n")
        if config.oidc is None:
            parser.exit(1, "hub mode needs an [oidc] table: viewers sign in before anything is drawn\n")
        try:
            gate = oidc.build(config.oidc, os.environ, instance_tokens)
            hub.prepare(config.database_url)
        except (ValueError, hub.HubError) as exc:  # HubError is a ValueError, named for the reader
            parser.exit(1, f"{exc}\n")
    elif config.oidc is not None:
        parser.exit(1, "[oidc] gates a hub: start one with `starpulse serve --hub`, or remove the table\n")
    base = args.config.parent if args.config else Path.cwd()
    if not (_STATIC / "index.html").is_file():
        parser.exit(1, f"{_STATIC} has no build; run `pnpm --filter flow-view build` first\n")
    adapters = [(instance, _adapter(parser, instance)) for instance in config.runs if instance.type]  # push-only: none
    starts = {instance.name: start for instance, adapter in adapters if (start := adapter.start(instance.url))}
    # Run now is drawn only for an instance whose adapter can start a run, and only on its run-safe workflows.
    reruns = {
        instance.name: rerun
        for instance, adapter in adapters
        if (factory := getattr(adapter, "rerun", None)) and (rerun := factory(instance.url))
    }
    run_safe = [name for name in config.qualified_run_safe() if name.partition("/")[0] in starts]
    if unstartable := sorted({t.start for t in config.triggers if t.start.partition("/")[0] not in starts}):
        parser.exit(1, f"triggers start workflows no adapter can start a run of: {', '.join(unstartable)}\n")
    try:
        board, feed = assemble(config, base, args.hours * 3600, run_safe)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    # Every reader keeps its own cursor over the one event log, so a second copy on another port sees every entry too.
    # The declared --hours is the default; an override Admin wrote beside the config replaces it from the first snapshot.
    url = database_url(config.database_url, base)
    log = EventLog(url)
    keep_event_log(log, config, base, hub=args.hub, stop=threading.Event())
    window = HistoryWindow(feed, args.hours, base / SETTINGS_FILE)
    # the history dates the lanes the board adapter replays, so it is open before the adapter starts
    store = history_store(config, base, feed.machines)
    feed.date_lanes(store.lane_path)
    if config.forward is not None:
        # before the adapter starts, so the history precedes the live changes in the log
        lane_events.replay(store, log)
    # a lane entry reaches the log for the hub it is forwarded to and for the triggers that start a run on it
    feed.record_lanes(store, log if config.forward is not None or config.triggers else None)
    feed.track_criteria(board.evaluate, store)
    threading.Thread(target=feed.keep_criteria, args=(threading.Event(),), name="board-criteria", daemon=True).start()
    feed.read_lanes(store.lane_rows)
    if args.hub:
        # The first pass runs before serving, so the hub never takes an event without today's partition.
        keeping = {"retention_days": config.hub_retention_days, "machines": machine_tables(feed.machines)}
        try:
            hub.maintain(log.engine, **keeping)
        except SQLAlchemyError as exc:
            parser.exit(1, f"hub maintenance failed at start: {exc}\n")
        threading.Thread(
            target=hub.keep,
            kwargs={"engine": log.engine, "stop": threading.Event(), **keeping},
            name="hub-maintenance",
            daemon=True,
        ).start()
    board.start(feed, f"flow-view-{args.port}", log)
    # a move the feed applied but never recorded (a restart between the two) is put in the history once the replay is read
    threading.Thread(target=reconcile_lanes, args=(feed, store), name="lane-reconcile", daemon=True).start()
    tasks = MachineTasks(feed, board.keys)
    follow(tasks, log, machine_events.STREAM, tasks.handle_entry)
    pulls = PullStore(log.engine)
    pins = GitHub()  # one memo of the pointer reads for the pull request projection and the release of dependents
    if shutil.which("gh"):  # without the GitHub CLI there is no source, and a task simply carries no PR state
        pull_requests = PullRequests(
            feed, pulls, repos=config.repos, pins=pins, trail=CiTrail(log) if config.ci else None
        )
        sync = PullSync(pulls, feed, config.repos, project=pull_requests.refresh)
        threading.Thread(target=sync.run_forever, name="pull-store", daemon=True).start()
    if config.release is not None:
        lanes = {state["id"] for state in feed.machines["board"]["states"]}
        if board.edit is None or not {WAITING, READY} <= lanes:
            parser.exit(1, "[release] needs a board that edits tasks and draws waiting and ready lanes\n")
        releaser = Releaser(feed, pulls, board.edit, config.repos, config.release.settle, pins)
        threading.Thread(target=_keep_released, args=(releaser, feed), name="board-release", daemon=True).start()
    for instance, adapter in adapters:
        adapter.follow(instance.url, feed.runs(instance.name), log)
    threading.Thread(
        target=record_machine_events, args=(store, log, threading.Event()), name="machine-history", daemon=True
    ).start()
    if args.hub:  # the lane changes the hub's sources forward become its Board trajectories
        threading.Thread(
            target=record_lane_events, args=(store, log, threading.Event()), name="lane-history", daemon=True
        ).start()
    if config.triggers:
        threading.Thread(
            target=run_triggers,
            args=(config.triggers, starts, store, log, threading.Event()),
            name="board-triggers",
            daemon=True,
        ).start()
    # The learned step graphs persist only in StarPulse's own store.
    pushed = PushRuns(feed.runs(PUSHED_INSTANCE), store)
    follow(pushed, log, run_events.STREAM, pushed.handle_entry)
    forwarding = threading.Event()  # never set: the forwarder lives as long as the process
    try:
        forwarder = forward.build(
            config,
            base,
            log,
            store,
            os.environ,
            hub=args.hub,
        )
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    insights = None
    if args.hub and config.oidc.engine_token_env:  # an engine writes findings only to a hub that names its token
        store = InsightStore(url, engine=log.engine)
        restore(store, feed)
        insights = Insights(store, feed)
    if forwarder is not None:
        forward.start(forwarder, forwarding)
    announce(args.port, feed.snapshot()["hint"])
    autopilot_runtime = start_autopilot(
        config, base, feed, board, store, config.level if args.hub else None, threading.Event()
    )
    handler = request_handler(
        feed,
        _STATIC,
        starts,
        run_safe,
        store,
        window,
        board.writer or _no_writer,
        config.harnesses,
        board.assign or _no_writer,
        starter(config.session_start_url),
        board.read,
        board.edit,
        board.archive,
        board.create,
        ingest=Ingest(instance_tokens, log) if instance_tokens else None,
        gate=gate,
        forward=ForwardIngest(source_tokens, log, aggregates_only=config.aggregates_only) if source_tokens else None,
        level=config.level if args.hub else None,
        insights=insights,
        forwarding=forwarder,
        reruns=reruns,
        contract=_cached(lambda: doctor.contract(feed.snapshot(), config, doctor.LIVE), _CONTRACT_TTL_S),
        milestones=board,
        pulls=pulls,
        telemetry=TelemetryLog(log),
        autopilot=autopilot_runtime,
    )
    serve_until_stopped(StarPulseServer((args.host, args.port), handler), feed)


if __name__ == "__main__":
    main()
