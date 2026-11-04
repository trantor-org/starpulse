"""UI smoke: every /api call the page makes within 50 ms p95, every modal fully drawn within 500 ms p95 of a cold click.

Run after a deploy against the live page. In Chrome, through Playwright, it opens the board and each of seven modals
`--rounds` times, every round on a freshly loaded page and with a click that no hover came before, so nothing was read or
drawn ahead (`bench/page_latency.py` hovers first). A modal's time runs from the click to its `starpulse:modal-drawn`
mark, which `web/src/shared/modalMark.ts` sets the frame after the dialog holds its full content. The In Progress
drill-in has no button to click (the Star Map's sun opens it), so a page loaded with its address is timed: its time runs from the page's first paint (`starpulse:board-drawn`) to its mark, and is 0 when it drew first.
`/api` calls come from Resource Timing, the event stream excluded: a call that finished with no timing, or failed, is a
failure, not a skipped sample. Prints one JSON verdict and exits 1 on any breach.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

API_P95_MS = 50.0
MODAL_P95_MS = 500.0
ROUNDS = 4
BUDGET_S = 150.0
MARK_TIMEOUT_MS = 5_000
STREAM = "/api/events"
MARK = "starpulse:modal-drawn"
BOARD_MARK = "starpulse:board-drawn"


@dataclass(frozen=True)
class Modal:
    name: str
    view: str  # the query the page loads
    sel: str  # the element a cold click lands on
    text: str  # its text begins with this, or any when empty
    label: str  # the opened dialog's aria-label matches this


MODALS = (
    Modal("Task view", "view=kanban", "#cols .card[data-id]", "", r"^[A-Z]+-\d+ "),
    Modal("New task", "view=kanban", "button.tbtn", "+ New task", r"^New task$"),
    Modal("Start-session confirm", "view=kanban", 'button.play[aria-label^="Start "]:not([disabled])', "", r"^Start "),
    Modal("Connect a tracker", "view=admin", "button.btn", "Connect a tracker", r"^Connect a tracker$"),
    Modal("DAG modal", "view=jobs", ".drow[data-dag]", "", r".+"),
    Modal("In Progress drill-in", "view=constellation&drill={card}", "", "", r"^In Progress drill-in$"),
    Modal("Admin theme confirm", "view=admin", "button.tile.add", "+Import scheme", r"^Import a color scheme$"),
)

_PROBE = """(() => {
  window.__ui = { drawn: [], api: [] };
  const mark = new PerformanceObserver((l) => { for (const e of l.getEntries())
    window.__ui.drawn.push({ t: e.startTime, label: (e.detail && e.detail.label) || "" }); });
  mark.observe({ type: "mark", buffered: true });
  const res = new PerformanceObserver((l) => { for (const e of l.getEntries()) {
    const p = new URL(e.name).pathname;
    if (p.startsWith("/api/") && p !== "/api/events") window.__ui.api.push({ path: p, ms: e.responseEnd - e.startTime, end: e.responseEnd }); } });
  res.observe({ type: "resource", buffered: true });
})();"""

_TARGET = """(spec) => {
  const el = [...document.querySelectorAll(spec.sel)].find((e) => !spec.text || e.textContent.trim().startsWith(spec.text));
  return el && !el.closest("[inert]") && !el.disabled ? el : null;
}"""

_CLICK = """(spec) => {
  const el = [...document.querySelectorAll(spec.sel)].find((e) => !spec.text || e.textContent.trim().startsWith(spec.text));
  const t = performance.now();
  el.click();
  return t;
}"""

_DRAWN = """([t, label]) => window.__ui.drawn.find((d) => d.t >= t && new RegExp(label).test(d.label))?.t ?? null"""


def percentile(samples: Sequence[float], pct: float) -> float | None:
    """The nearest-rank percentile, or None for no samples."""
    if not samples:
        return None
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def verdict(
    modals: dict[str, list[float]], api: dict[str, list[float]], problems: Sequence[str], elapsed_s: float
) -> dict:
    """The JSON artifact: each modal's and each route's p95 against its budget, and every problem that fails the run."""
    shown = {
        name: {"samples": [round(s, 1) for s in samples], "p95_ms": percentile(samples, 95), "budget_ms": MODAL_P95_MS}
        for name, samples in modals.items()
    }
    routes = {
        path: {"n": len(samples), "p95_ms": percentile(samples, 95), "budget_ms": API_P95_MS}
        for path, samples in api.items()
    }
    breaches = [
        f"{name}: p95 {row['p95_ms']} ms over {MODAL_P95_MS:g} ms"
        for name, row in shown.items()
        if row["p95_ms"] is not None and row["p95_ms"] > MODAL_P95_MS
    ] + [
        f"{path}: p95 {row['p95_ms']:.1f} ms over {API_P95_MS:g} ms"
        for path, row in routes.items()
        if row["p95_ms"] is not None and row["p95_ms"] > API_P95_MS
    ]
    missing = [f"{name}: no sample" for name, samples in modals.items() if not samples]
    failures = [*breaches, *missing, *problems]
    return {"ok": not failures, "failures": failures, "modals": shown, "api": routes, "elapsed_s": round(elapsed_s, 1)}


def route(path: str) -> str:
    """The route a path belongs to: its ids and hashes become `*`, so one route's calls share a p95."""
    return "/".join(
        "*" if re.fullmatch(r"(TASK|task)-\d+|[0-9a-f]{12,}|\d+", part) else part for part in path.split("/")
    )


def _board_card(page, base: str) -> str | None:
    page.goto(f"{base}/?view=kanban", wait_until="domcontentloaded")
    try:
        page.wait_for_selector("#cols .card[data-id]", timeout=10_000)
    except Exception:
        return None
    return page.evaluate("document.querySelector('#cols .card[data-id]').dataset.id")


def _collect(page, api: dict[str, list[float]], problems: list[str], finished: list[str]) -> None:
    page.wait_for_timeout(400)
    timed = page.evaluate("window.__ui.api")
    seen: dict[str, int] = defaultdict(int)
    for call in timed:
        seen[route(call["path"])] += 1
        if call["end"] <= 0:
            problems.append(f"{route(call['path'])}: untimed request")
        else:
            api[route(call["path"])].append(call["ms"])
    for path in sorted(set(finished)):
        wanted = finished.count(path)
        if seen[path] < wanted:
            problems.append(f"{path}: {wanted - seen[path]} request(s) finished with no timing")


def local_file(assets: Path, url: str) -> Path:
    """The file in a local build that answers a page URL: an `/assets/` file by its path, any other page the index."""
    path = urlsplit(url).path
    return assets / path.lstrip("/") if path.startswith("/assets/") else assets / "index.html"


def run(base: str, rounds: int, channel: str, budget_s: float, assets: Path | None = None) -> dict:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415 - the bench group only

    started = time.monotonic()
    modals: dict[str, list[float]] = {m.name: [] for m in MODALS}
    api: dict[str, list[float]] = defaultdict(list)
    problems: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=channel, headless=True)
        # The page is timed, not its certificate: the system Chrome does not read the system store the private CA is in.
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, ignore_https_errors=True)
        page.add_init_script(_PROBE)
        if assets is not None:  # a branch's own build, drawing the server's live data
            page.route(
                lambda u: u.startswith(base) and not urlsplit(u).path.startswith("/api/"),
                lambda hit: hit.fulfill(path=str(local_file(assets, hit.request.url))),
            )
        finished: list[str] = []

        def on_finished(request) -> None:
            path = urlsplit(request.url).path
            if path.startswith("/api/") and path != STREAM:
                finished.append(route(path))

        def on_failed(request) -> None:
            path = urlsplit(request.url).path
            if path.startswith("/api/") and path != STREAM:
                problems.append(f"{path}: request failed ({request.failure})")

        def on_response(response) -> None:
            path = urlsplit(response.url).path
            if path.startswith("/api/") and path != STREAM and response.status >= 400:
                problems.append(f"{path}: status {response.status}")

        page.on("requestfinished", on_finished)
        page.on("requestfailed", on_failed)
        page.on("response", on_response)
        card = _board_card(page, base)
        if card is None:
            problems.append("board: drew no cards in 20 s")
        for modal in MODALS:
            for _ in range(rounds):
                if time.monotonic() - started > budget_s:
                    problems.append(f"{modal.name}: out of the {budget_s:g} s budget before its round")
                    break
                if "{card}" in modal.view and card is None:
                    break
                page.goto(f"{base}/?{modal.view.format(card=card)}", wait_until="domcontentloaded")
                finished.clear()
                try:
                    if modal.sel:
                        spec = {"sel": modal.sel, "text": modal.text}
                        page.wait_for_function(f"(spec) => !!({_TARGET})(spec)", arg=spec, timeout=10_000)
                        clicked = page.evaluate(_CLICK, spec)
                    else:
                        page.wait_for_function(
                            f"() => performance.getEntriesByName('{BOARD_MARK}').length > 0", timeout=10_000
                        )
                        clicked = 0
                    page.wait_for_function(
                        f"(a) => !!({_DRAWN})(a)", arg=[clicked, modal.label], timeout=MARK_TIMEOUT_MS
                    )
                    drawn = page.evaluate(_DRAWN, [clicked, modal.label])
                    start = clicked or page.evaluate(f"performance.getEntriesByName('{BOARD_MARK}')[0].startTime")
                    modals[modal.name].append(max(0.0, drawn - start))
                except Exception as exc:
                    problems.append(f"{modal.name}: did not draw ({str(exc).splitlines()[0][:120]})")
                _collect(page, api, problems, finished)
        browser.close()
    return verdict(modals, api, list(dict.fromkeys(problems)), time.monotonic() - started)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("url", help="the StarPulse page, such as https://localhost:8766")
    parser.add_argument("--rounds", type=int, default=ROUNDS, help="cold loads and clicks per modal")
    parser.add_argument("--channel", default="chrome", help="the Playwright browser channel to drive")
    parser.add_argument("--budget-s", type=float, default=BUDGET_S, help="seconds before the run gives up its rounds")
    parser.add_argument("--assets", type=Path, help="serve the page from this local build (`vite build --outDir`)")
    args = parser.parse_args(argv)
    result = run(args.url.rstrip("/"), args.rounds, args.channel, args.budget_s, args.assets)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
