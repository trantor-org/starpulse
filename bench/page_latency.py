"""Page latency: every request and page surface of a running StarPulse, timed against the latency budget.

The budget (trantor ADR "StarPulse Holds a Latency Budget on Every Request and Frame"): every request, interaction
and stream delivery within 50 ms at p95, every animation frame's work within 16.7 ms at p95. This script times:

- each read route, called directly `--samples` times, with the parameters it needs drawn from the server's snapshot;
- the event stream's first `snapshot`, from connect to the end of that event;
- in Chrome, through Playwright: the first paint of the board, each view switch, opening a task's modal on the Kanban
  until its record has painted, and the Star Map's level fly-to, each from the input to the second animation frame
  after it; every stream event from its arrival to the next frame; the page's own animation-frame work; and every
  main-thread task over 50 ms.

The page's own `/api` requests are recorded too, and a request the page made that no row times fails the run: a
surface the harness does not know about reads as missing, never as fast. It only reads; the write routes are left
to the soak and the gate's seeded server. It prints one row per surface with p50, p95 and the
budget, and exits 1 when any row is over budget or untimed.

Run it from the repository root with ``uv run --group bench python bench/page_latency.py <url> [--json FILE]``. It
drives the system Chrome (``--channel``), so Playwright's own browser download is not needed. ``--assets DIR`` draws the
page from a local build instead of the server's, so a branch's page change is timed against live data before it ships.

``--viewer`` times the page as a viewer's own machine would draw it while the server stays under its host's load: the
bench, its Chrome included, re-runs in a user systemd scope weighted far over the host's other work, since a viewer's
browser does not share the server's CPU. Without it, a loaded host starves the measuring browser too, and even a
click that draws nothing new reads over budget. That weight counts only against the scope's siblings, so work in
another slice, such as a Docker container, can still starve it: the run reads its scope's own ``cpu.pressure`` before
and after, and a run whose scope waited for CPU over ``STARVED_SHARE`` of its time is marked STARVED and exits 2, a
measure of the host and not of the page, neither a pass nor a failure.

``--cpu-throttle N`` slows the page's CPU N times (Chrome's ``Emulation.setCPUThrottlingRate``) once the board has
painted for the first time, so the interactions after it are timed on a slower machine than the bench's: a click that
waits behind steady-state stream work reads N times longer, where a click that does its own work in 10 ms reads 10 N.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import re
import sys
import time
import urllib.parse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

#: p95 budget of a request, an interaction and a stream delivery, in ms.
BUDGET_MS = 50.0
#: p95 budget of one animation frame's work, in ms (60 fps).
FRAME_BUDGET_MS = 1000 / 60
#: The gap between two frames that means one was dropped: a frame on time leaves about 16.7 ms, jitter included.
DROPPED_MS = 1.5 * FRAME_BUDGET_MS
#: A main-thread task this long delays any input that lands during it past the budget.
LONG_TASK_MS = 50.0
#: The pointer's rest on a card before it clicks: a viewer's hand slows onto a target before pressing it.
HOVER_MS = 150
#: The `--viewer` scope's CPU weight, against the default 100 of every other unit on the host.
VIEWER_CPU_WEIGHT = 10_000
#: Set inside the `--viewer` scope, so the bench enters it once.
VIEWER_ENV = "STARPULSE_BENCH_VIEWER"
#: The share of a `--viewer` run its scope's tasks may wait for CPU (`cpu.pressure` some) before the run is starved.
STARVED_SHARE = 0.05
#: The exit of a starved run: it measured the host's load, not the page.
STARVED = 2

#: The read routes and how to build each one's path from what the snapshot holds; `{task}`, `{milestone}` and `{doc}`
#: are filled from the server's own records, `{from}` and `{to}` from `--what-if`.
#: The states the what-if reads on the live Backlog board; the gate's seeded board spells its states as lane ids.
WHAT_IF = ("Ready", "In Progress")
READS: dict[str, str] = {
    "/api/snapshot": "/api/snapshot",
    "/api/merges": "/api/merges?limit=20",
    "/api/pulls": "/api/pulls",
    "/api/doctor": "/api/doctor",
    "/api/machines": "/api/machines?limit=20",
    "/api/history": "/api/history?task={task}",
    "/api/analytics/health": "/api/analytics/health",
    "/api/level": "/api/level?hours=168",
    "/api/level/trajectories": "/api/level/trajectories?hours=168",
    "/api/level/what-if": "/api/level/what-if?hours=168&from={from}&to={to}&p=0.5",
    "/api/harnesses": "/api/harnesses",
    "/api/task/<id>": "/api/task/{task}",
    "/api/milestones": "/api/milestones",
    "/api/milestones/<id>": "/api/milestones/{milestone}",
    "/api/docs": "/api/docs",
    "/api/docs/<id>": "/api/docs/{doc}",
    "/api/forwarding": "/api/forwarding",
    "/api/history-window": "/api/history-window",
    "/api/events/body/<id>": "/api/events/body/{snapshot}",
}

#: Where a path segment is a record's id, so `/api/task/TASK-9` and `/api/task/TASK-10` are one surface.
_ID_ROUTES = ("/api/task/", "/api/milestones/", "/api/docs/", "/api/insights/", "/api/events/body/")


@dataclass
class Row:
    """One surface: its samples in ms and the p95 it must stay under."""

    name: str
    kind: str
    budget: float
    samples: list[float] = field(default_factory=list)
    note: str = ""

    @property
    def p50(self) -> float | None:
        return percentile(self.samples, 50)

    @property
    def p95(self) -> float | None:
        return percentile(self.samples, 95)

    @property
    def over(self) -> bool:
        p95 = self.p95
        return p95 is not None and p95 > self.budget


def percentile(samples: Sequence[float], pct: float) -> float | None:
    """The nearest-rank percentile, or None for no samples."""
    if not samples:
        return None
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def surface(url: str) -> str | None:
    """The route a request is one sample of: its `/api` path, query dropped, a record's id as `<id>`; None outside `/api`."""
    path = urllib.parse.urlsplit(url).path
    if not path.startswith("/api/"):
        return None
    for prefix in _ID_ROUTES:
        rest = path[len(prefix) :]
        if path.startswith(prefix) and rest and "/" not in rest and rest not in ("edit", "archive", "gone", "repo"):
            return f"{prefix}<id>"
    return path


def median_run(runs: Sequence[Sequence[Row]]) -> list[Row]:
    """One row per surface, from the run whose p95 is the median of that surface's runs (the lower of two).

    The validate lane is noisy: one starved run reads over budget on a surface that is fast in the others, and one lucky
    run reads under on a slow one. Judging the median run's p95 fails a surface only when most runs agree it is slow.
    Rows are matched by name, in the order they first appear; a surface a run did not sample (a stream event that run
    never saw) is judged on the runs that did, and one no run sampled keeps its note. Several runs say so in the note.
    """
    by_name: dict[str, list[Row]] = {}
    for run in runs:
        for row in run:
            by_name.setdefault(row.name, []).append(row)
    judged = []
    for rows in by_name.values():
        sampled = sorted((r for r in rows if r.samples), key=lambda r: r.p95 or 0.0)
        if not sampled:
            judged.append(rows[0])
        elif len(runs) == 1:
            judged.append(sampled[0])
        else:
            median = sampled[(len(sampled) - 1) // 2]
            note = f"median of {len(runs)} runs, p95 {'/'.join(f'{r.p95:.0f}' for r in sampled)}"
            judged.append(
                Row(median.name, median.kind, median.budget, median.samples, f"{median.note}; {note}".strip("; "))
            )
    return judged


def apply_ceilings(rows: Sequence[Row], ceilings: Sequence[str]) -> None:
    """Raise the budget of each row named in `ceilings` (`NAME=MS`) and say so in its note.

    A ceiling is a known overrun held where it is: the row still fails past it, so it cannot get worse, and the note
    keeps the overrun visible until the work that closes it lands and the ceiling is dropped.
    """
    by_name = {row.name: row for row in rows}
    for ceiling in ceilings:
        name, _, ms = ceiling.rpartition("=")
        if name not in by_name:
            raise ValueError(f"no row named {name}")
        row = by_name[name]
        row.budget = float(ms)
        row.note = (
            f"{row.note}; ceiling {float(ms):.0f} ms, over the {BUDGET_MS:.0f} ms budget until its fix lands".strip(
                "; "
            )
        )


def untimed(requested: Iterable[str], timed: Iterable[str]) -> list[str]:
    """The surfaces the page requested that no row times, sorted."""
    known = set(timed)
    return sorted({s for url in requested if (s := surface(url)) and s not in known})


def starved(waited: float | None) -> bool:
    """Whether a run whose scope waited for CPU that share of its time measured a starved browser."""
    return waited is not None and waited > STARVED_SHARE


def verdict(rows: Sequence[Row], missing: Sequence[str], waited: float | None = None) -> int:
    """STARVED for a starved run; else 0 when every row is under its budget and the page made no untimed request, else 1."""
    if starved(waited):
        return STARVED
    return 1 if missing or any(r.over for r in rows) else 0


def table(rows: Sequence[Row], missing: Sequence[str], waited: float | None = None) -> str:
    """The rows as a fixed-width table, over-budget rows marked, then the untimed requests and a starved run's mark."""
    fmt = "{:<44} {:<12} {:>6} {:>9} {:>9} {:>7}  {}"
    out = [fmt.format("surface", "kind", "n", "p50 ms", "p95 ms", "budget", "")]

    def ms(v: float | None) -> str:
        return "-" if v is None else f"{v:.1f}"

    for r in rows:
        mark = "OVER" if r.over else ""
        out.append(
            fmt.format(
                r.name, r.kind, len(r.samples), ms(r.p50), ms(r.p95), f"{r.budget:.1f}", f"{mark} {r.note}".strip()
            )
        )
    out.extend(f"UNTIMED request the page made: {s}" for s in missing)
    if starved(waited):
        out.append(
            f"STARVED: the viewer scope waited for CPU {waited:.0%} of the run, over {STARVED_SHARE:.0%}; "
            "its rows measure the host's load, not the page"
        )
    return "\n".join(out)


def fill(template: str, ids: dict[str, str]) -> str | None:
    """`template` with its `{name}` holes filled from `ids`, or None when one has no id to fill it."""
    names = re.findall(r"\{(\w+)\}", template)
    if any(n not in ids for n in names):
        return None
    return template.format(**{n: urllib.parse.quote(ids[n], safe="") for n in names})


def ids_of(snapshot: dict, milestones: object, docs: object) -> dict[str, str]:
    """A task, a milestone and a doc this server holds, to put in the routes that read one."""
    ids: dict[str, str] = {}
    for flow in snapshot.get("flows", []):
        for agent in flow.get("agents", []):
            if agent.get("id"):
                ids["task"] = agent["id"]
                break
        if "task" in ids:
            break
    for key, listing in (("milestone", milestones), ("doc", docs)):
        items = listing.get(f"{key}s", listing) if isinstance(listing, dict) else listing
        if isinstance(items, list) and items and isinstance(items[0], dict) and items[0].get("id"):
            ids[key] = items[0]["id"]
    return ids


# Everything below talks to a server and a browser; the rules above carry the tests.


class Client:
    """One kept-alive HTTP connection to the server, as the page's own fetches reuse one."""

    def __init__(self, base: str) -> None:
        parts = urllib.parse.urlsplit(base)
        self.host, self.port = parts.hostname or "127.0.0.1", parts.port or 80
        self.conn = http.client.HTTPConnection(self.host, self.port, timeout=60)

    def get(self, path: str) -> tuple[int, bytes, float]:
        start = time.perf_counter()
        try:
            self.conn.request("GET", path, headers={"accept": "application/json"})
            response = self.conn.getresponse()
            body = response.read()
        except http.client.HTTPException, OSError:
            self.conn.close()
            self.conn = http.client.HTTPConnection(self.host, self.port, timeout=60)
            raise
        return response.status, body, (time.perf_counter() - start) * 1000

    def json(self, path: str) -> object:
        status, body, _ = self.get(path)
        return json.loads(body) if status == 200 else {}


def time_reads(client: Client, samples: int, what_if: Sequence[str] = WHAT_IF) -> list[Row]:
    snapshot = client.json("/api/snapshot")
    ids = ids_of(
        snapshot if isinstance(snapshot, dict) else {}, client.json("/api/milestones"), client.json("/api/docs")
    )
    ids |= dict(zip(("from", "to"), what_if, strict=True))
    if key := ref_key(first_snapshot(f"http://{client.host}:{client.port}", "/api/events?snapshot=ref") or ""):
        ids["snapshot"] = key
    rows = []
    for name, template in READS.items():
        row = Row(name, "request", BUDGET_MS)
        path = fill(template, ids)
        if path is None:
            row.note = "no record to read"
            rows.append(row)
            continue
        statuses = set()
        for _ in range(samples):
            status, _, ms = client.get(path)
            statuses.add(status)
            row.samples.append(ms)
        if statuses - {200}:
            row.note = f"answered {sorted(statuses)}"
        rows.append(row)
    return rows


def ref_key(data: str) -> str | None:
    """The key a `snapshot` event sent by reference names (`ref /api/events/body/<key>`), None for one sent inline."""
    return data.removeprefix("ref /api/events/body/") if data.startswith("ref /api/events/body/") else None


def first_snapshot(base: str, path: str) -> str | None:
    """The data of the first `snapshot` event the stream at `path` sends."""
    parts = urllib.parse.urlsplit(base)
    conn = http.client.HTTPConnection(parts.hostname or "127.0.0.1", parts.port or 80, timeout=60)
    try:
        conn.request("GET", path, headers={"accept": "text/event-stream"})
        response, event = conn.getresponse(), None
        while line := response.fp.readline():
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if text.startswith("event:"):
                event = text[6:].strip()
            elif text.startswith("data:") and event == "snapshot":
                return text[5:].strip()
        return None
    finally:
        conn.close()


def time_stream(base: str, samples: int) -> Row:
    """Connect to the event stream and time its first `snapshot` event to the end of its data."""
    row = Row("/api/events", "stream", BUDGET_MS, note="connect to first snapshot")
    parts = urllib.parse.urlsplit(base)
    for _ in range(samples):
        conn = http.client.HTTPConnection(parts.hostname or "127.0.0.1", parts.port or 80, timeout=60)
        start = time.perf_counter()
        conn.request("GET", "/api/events", headers={"accept": "text/event-stream"})
        response = conn.getresponse()
        event = None
        while True:
            line = response.fp.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if text.startswith("event:"):
                event = text[6:].strip()
            elif text == "" and event == "snapshot":
                row.samples.append((time.perf_counter() - start) * 1000)
                break
        conn.close()
    return row


#: Installed before the page's own scripts. It records on `window.__sp`: the first frame that shows the Board, each
#: later stream event's arrival to the next frame, the page's own animation-frame work, every long task, and a way to await a fetch's body.
_PROBE = """
(() => {
  const sp = (window.__sp = { deliveries: [], frames: [], longTasks: [], waits: [] });
  // the page marks the first frame that shows the Board (src/shared/boardDrawn.ts): ms from navigation, null until then
  Object.defineProperty(sp, "firstPaint", { get: () => performance.getEntriesByName("starpulse:board-drawn")[0]?.startTime ?? null });
  const raf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = (cb) => raf((t) => { const s = performance.now(); try { cb(t); } finally { sp.frames.push(performance.now() - s); } });
  sp.twoFrames = () => new Promise((r) => raf(() => raf(() => r(performance.now()))));
  const ES = window.EventSource;
  window.EventSource = function (url, init) {
    const src = new ES(url, init);
    const add = src.addEventListener.bind(src);
    src.addEventListener = (type, fn, opts) => add(type, (e) => {
      const at = performance.now();
      fn(e);
      raf(() => {
        if (type !== "snapshot") sp.deliveries.push([type, performance.now() - at]);
      });
    }, opts);
    return src;
  };
  window.EventSource.prototype = ES.prototype;
  const f = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const res = await f(input, init);
    const url = typeof input === "string" ? input : input.url;
    res.clone().arrayBuffer().finally(() => {
      for (const w of sp.waits.filter((w) => url.includes(w.part))) w.resolve();
      sp.waits = sp.waits.filter((w) => !url.includes(w.part));
    });
    return res;
  };
  sp.fetched = (part) => new Promise((resolve) => sp.waits.push({ part, resolve }));
  try {
    new PerformanceObserver((list) => { for (const e of list.getEntries()) sp.longTasks.push(e.duration); })
      .observe({ type: "longtask", buffered: true });
  } catch {}
})();
"""

#: Click `sel` and resolve with the ms from the click to the second frame after it, or null when it is not on the page.
_CLICK = """async (sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const s = performance.now();
  el.click();
  return (await window.__sp.twoFrames()) - s;
}"""

#: Open a task's card and resolve with the ms from the click to the second frame after its modal drew the full record:
#: the dialog clears `aria-busy` once it holds the record, whether a hover read it ahead or the click did. A dialog
#: drawn ahead of the click waits inert, so only one outside an `[inert]` counts as shown; whether one waited is returned
#: too. A build from before that marker ends where it always did, at the record's response.
_OPEN = """async (id) => {
  const el = document.querySelector(`#cols .card[data-id="${id}"]`);
  if (!el) return null;
  const got = window.__sp.fetched(`/api/task/${encodeURIComponent(id)}`);
  const drawn = () => [...document.querySelectorAll("[role=dialog][aria-busy=false]")].some((d) => !d.closest("[inert]"));
  const ahead = !!document.querySelector("[inert] [role=dialog]");
  const s = performance.now();
  el.click();
  await new Promise((resolve) => {
    const seen = new MutationObserver(() => drawn() && done());
    const cap = setTimeout(() => done(), 30000);
    const done = () => { seen.disconnect(); clearTimeout(cap); resolve(); };
    got.then(() => { const d = document.querySelector("[role=dialog]"); if (d && !d.hasAttribute("aria-busy")) done(); });
    if (drawn()) return done();
    seen.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["aria-busy", "inert"] });
  });
  return { ms: (await window.__sp.twoFrames()) - s, ahead };
}"""
#: True once no dialog shows: one drawn ahead of a click waits inert.
_SHOWN_GONE = """() => ![...document.querySelectorAll("[role=dialog]")].some((d) => !d.closest("[inert]"))"""
#: The ms between frames for `ms` after clicking `sel`: what an animation it starts looks like.
_INTERVALS = """async ([sel, ms]) => {
  const el = document.querySelector(sel);
  if (!el) return [];
  const raf = (cb) => window.requestAnimationFrame(cb);
  const out = [];
  let last = performance.now();
  const end = last + ms;
  el.click();
  await new Promise((done) => { const tick = (t) => { const now = performance.now(); out.push(now - last); last = now; now < end ? raf(tick) : done(); }; raf(tick); });
  return out;
}"""

#: Each nav button by the view it opens; `title^=` matches the Flow graph's longer title.
VIEWS = {"Kanban": "Kanban", "DAGs": "DAGs", "Admin": "Admin", "Flow graph": "Flow graph", "Star Map": "Star Map"}


def _nav(title: str) -> str:
    return f'#nav button.node[title^="{title}"]'


def local_file(assets: Path, url: str) -> Path:
    """The file in a local build that answers a page URL: an `/assets/` file by its path, any other page the index."""
    path = urllib.parse.urlsplit(url).path
    return assets / path.lstrip("/") if path.startswith("/assets/") else assets / "index.html"


def time_page(
    base: str,
    samples: int,
    channel: str,
    requested: list[str],
    assets: Path | None = None,
    cpu_throttle: float = 1.0,
) -> list[Row]:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415 - the bench group only

    rows: list[Row] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=channel, headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.add_init_script(_PROBE)
        if assets is not None:  # a branch's own build, drawing the server's live data
            page.route(
                lambda u: u.startswith(base) and surface(u) is None,
                lambda route: route.fulfill(path=str(local_file(assets, route.request.url))),
            )
        page.on("request", lambda r: requested.append(r.url))

        load = Row(
            "first paint of the board",
            "interaction",
            BUDGET_MS,
            note="navigation to the frame that draws the board (starpulse:board-drawn)",
        )
        for _ in range(max(1, samples // 4)):
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("window.__sp && window.__sp.firstPaint !== null", timeout=60_000)
            load.samples.append(page.evaluate("window.__sp.firstPaint"))
        rows.append(load)
        if cpu_throttle > 1:  # after first paint, so the load row stays the unthrottled one
            page.context.new_cdp_session(page).send("Emulation.setCPUThrottlingRate", {"rate": cpu_throttle})
        page.wait_for_timeout(1000)

        for name, title in VIEWS.items():
            row = Row(f"switch to {name}", "interaction", BUDGET_MS)
            away = _nav("DAGs" if title == "Kanban" else "Kanban")
            for _ in range(samples):
                page.evaluate(_CLICK, away)
                ms = page.evaluate(_CLICK, _nav(title))
                if ms is not None:
                    row.samples.append(ms)
            row.note = "" if row.samples else "button not found"
            rows.append(row)

        modal = Row(
            "open a task's modal",
            "interaction",
            BUDGET_MS,
            note=f"click, after a {HOVER_MS} ms hover, to the frame after its full record",
        )
        page.evaluate(_CLICK, _nav("Kanban"))
        # The switch sample ends after two frames; React deliberately takes ownership after the reveal window.
        # Modal interaction must wait for that bookkeeping instead of clicking the still-inert kept surface.
        page.wait_for_function("() => !document.querySelector('[data-view=kanban]')?.hasAttribute('inert')", timeout=10_000)
        page.wait_for_selector("#cols .card[data-id]", timeout=30_000)
        ahead = 0
        for task in page.eval_on_selector_all(
            "#cols .card[data-id]", "els => els.filter(e => e.checkVisibility()).map(e => e.dataset.id)"
        )[:samples]:
            card = page.locator(f'#cols .card[data-id="{task}"]:visible').first
            if not card.count():
                continue
            card.hover()
            page.wait_for_timeout(HOVER_MS)
            opened = page.evaluate(_OPEN, task)
            if opened is not None:
                modal.samples.append(opened["ms"])
                ahead += opened["ahead"]
            # Closing is outside the measurement. Use the modal's explicit close control so a task that
            # happens to be editing cannot consume Escape and leave the dialog open for the next sample.
            page.locator('[role="dialog"]:visible button[aria-label="Close"]').click(timeout=10_000)
            # the pointer still rests on the card, so its modal may be drawn again, hidden and inert, for the next click
            page.wait_for_function(_SHOWN_GONE, timeout=10_000)
        modal.note += f"; {ahead} of {len(modal.samples)} drawn ahead"
        rows.append(modal)

        fly = Row("Star Map fly-to start", "interaction", BUDGET_MS, note="click on Star Map while it shows")
        flight = Row(
            "Star Map fly-to frame interval",
            "frame",
            DROPPED_MS,
            note="ms between frames for 1.5 s; over is a dropped frame",
        )
        for _ in range(max(1, samples // 4)):
            page.evaluate(_CLICK, _nav("Kanban"))
            page.evaluate(_CLICK, _nav("Star Map"))
            page.wait_for_timeout(1500)
            ms = page.evaluate(_CLICK, _nav("Star Map"))
            if ms is not None:
                fly.samples.append(ms)
            page.wait_for_timeout(1500)
            page.evaluate(_CLICK, _nav("Kanban"))
            page.evaluate(_CLICK, _nav("Star Map"))
            page.wait_for_timeout(1500)
            flight.samples.extend(page.evaluate(_INTERVALS, [_nav("Star Map"), 1500]))
        rows += [fly, flight]

        page.wait_for_timeout(2000)
        probe = page.evaluate(
            "({deliveries: window.__sp.deliveries, frames: window.__sp.frames, longTasks: window.__sp.longTasks})"
        )
        by_type: dict[str, list[float]] = {}
        for kind, ms in probe["deliveries"]:
            by_type.setdefault(kind, []).append(ms)
        rows += [Row(f"stream `{kind}` to paint", "stream", BUDGET_MS, ms) for kind, ms in sorted(by_type.items())]
        rows.append(Row("page animation-frame work", "frame", FRAME_BUDGET_MS, probe["frames"]))
        # every entry is a task over 50 ms, so one is enough to put the row over
        rows.append(Row("main-thread tasks over 50 ms", "frame", LONG_TASK_MS, probe["longTasks"]))
        browser.close()
    return rows


def viewer_command(argv: Sequence[str], python: str) -> list[str]:
    """This bench's own command line, run in a user scope that outweighs the host's other work."""
    return ["systemd-run", "--user", "--scope", "--quiet", "-p", f"CPUWeight={VIEWER_CPU_WEIGHT}", "--", python, *argv]


def pressure_total(text: str) -> int:
    """The `some` line's `total`: the µs at least one of the cgroup's tasks waited for CPU."""
    some = next(line for line in text.splitlines() if line.startswith("some "))
    return int(some.rsplit("total=", 1)[1])


def waited(before: int, after: int, seconds: float) -> float:
    """The share of `seconds` the cgroup's tasks waited for CPU, from its `some` totals before and after."""
    return (after - before) / (seconds * 1e6)


def scope_pressure() -> int | None:
    """This process's own cgroup's `some` CPU-pressure total, or None where it cannot be read."""
    try:
        group = Path("/proc/self/cgroup").read_text().strip().rsplit(":", 1)[1]
        return pressure_total((Path("/sys/fs/cgroup") / group.lstrip("/") / "cpu.pressure").read_text())
    except (OSError, IndexError, StopIteration, ValueError):
        return None


def enter_viewer(argv: Sequence[str]) -> None:
    """Re-run this bench inside its `--viewer` scope, unless it already runs there."""
    if os.environ.get(VIEWER_ENV):
        return
    os.environ[VIEWER_ENV] = "1"
    command = viewer_command(argv, sys.executable)
    os.execvp(command[0], command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("url", help="the StarPulse page, such as http://127.0.0.1:8766")
    parser.add_argument("--samples", type=int, default=20, help="samples per surface")
    parser.add_argument("--channel", default="chrome", help="the Playwright browser channel to drive")
    parser.add_argument("--no-page", action="store_true", help="time the requests only")
    parser.add_argument(
        "--what-if",
        nargs=2,
        metavar=("FROM", "TO"),
        default=WHAT_IF,
        help="the two states /api/level/what-if is asked about, as the server spells them (default: the live board's)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="run the whole measurement this many times and judge each surface on the median run's p95 (the CI gate uses 3)",
    )
    parser.add_argument(
        "--ceiling",
        action="append",
        default=[],
        metavar="ROW=MS",
        help="hold a row with a known overrun to MS until its fix lands (repeatable); the row still fails past it",
    )
    parser.add_argument(
        "--assets",
        type=Path,
        help="serve the page from this local build (`vite build --outDir`), its /api from the URL",
    )
    parser.add_argument(
        "--cpu-throttle",
        type=float,
        default=1.0,
        metavar="N",
        help="slow the page's CPU N times after its first paint (Chrome's CPU throttling rate); 1 leaves it as it is",
    )
    parser.add_argument("--json", type=argparse.FileType("w"), help="also write the rows here")
    parser.add_argument(
        "--viewer",
        action="store_true",
        help="time the page as a viewer's own machine draws it: run in a scope weighted over the host's load",
    )
    args = parser.parse_args(argv)
    if args.viewer:
        enter_viewer(sys.argv)
    base = args.url.rstrip("/")
    start, before = time.monotonic(), scope_pressure() if args.viewer else None

    requested: list[str] = []
    runs = []
    for _ in range(max(1, args.repeat)):
        run = time_reads(Client(base), args.samples, args.what_if)
        run.append(time_stream(base, max(1, args.samples // 4)))
        if not args.no_page:
            run.extend(time_page(base, args.samples, args.channel, requested, args.assets, args.cpu_throttle))
        runs.append(run)
    rows = median_run(runs)
    apply_ceilings(rows, args.ceiling)
    timed = [r.name for r in rows] + ["/api/events"]
    missing = untimed(requested, timed)
    after = scope_pressure() if before is not None else None
    share = waited(before, after, time.monotonic() - start) if before is not None and after is not None else None
    print(table(rows, missing, share))
    if args.json:
        json.dump(
            {
                "rows": [
                    {
                        "name": r.name,
                        "kind": r.kind,
                        "budget": r.budget,
                        "p50": r.p50,
                        "p95": r.p95,
                        "n": len(r.samples),
                        "over": r.over,
                        "note": r.note,
                    }
                    for r in rows
                ],
                "untimed": missing,
                "viewer_waited": share,
                "starved": starved(share),
            },
            args.json,
            indent=2,
        )
    return verdict(rows, missing, share)


if __name__ == "__main__":
    sys.exit(main())
