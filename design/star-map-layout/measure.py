"""Measure the Star Map Board as the page draws it: the shipped placement and route search beside each layout library, per board and viewport.

usage: python design/star-map-layout/measure.py http://localhost:PORT/star-map-layout/index.html [--vp WxH ...] [--lib L ...] [--board B ...]
           [--fs 100 125 150] [--shots DIR] [--json FILE]

Needs Playwright and a system Chrome. Every figure is read off the built page by mock.js's `window.__GRADE__()`, the same reading for
the shipped Board and every library: the sun's radius on screen (SUN_R * fit zoom), the paths joined rim to rim of the pairs the board
declares, the paths through another state's footprint, the paths over a name, the pairs of paths that cross, and the pairs of states out
of tier order. With every board measured it also prints, per library, the states that change side of the Board's middle when one state of
the demo board is switched off. Layout time, bundle size and licence are layouts.mjs's, which runs the libraries.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

LIBS = ["shipped", "dagre", "graphviz", "elk", "cola"]
BOARDS = ["base", "third-in-tier", "two-more-tiers", "fourteen", "unlisted", "three"]
STATES = ["new", "ready", "waiting", "in_progress", "review", "needs_attention", "done", "archived"]
VPS = ["1366x768", "1920x1080", "2560x1440", "3440x1440"]
ap = argparse.ArgumentParser()
ap.add_argument("url")
ap.add_argument("--vp", nargs="+", default=VPS)
ap.add_argument("--lib", nargs="+", default=LIBS)
ap.add_argument("--board", nargs="+", default=[*BOARDS, *(f"base~{s}" for s in STATES)])
ap.add_argument("--fs", nargs="+", default=["100"])
ap.add_argument("--shots")
ap.add_argument("--bright", action="store_true", help="redraw every path bright in the screenshots")
ap.add_argument("--json", type=Path)
a = ap.parse_args()
rows = []
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    for vp in a.vp:
        w, h = map(int, vp.split("x"))
        for lib in a.lib:
            for key in a.board:
                for fs in a.fs:
                    board, _, off = key.partition("~")
                    pg = b.new_page(viewport={"width": w, "height": h})
                    errs = []
                    pg.on("console", lambda m, errs=errs: m.type == "error" and errs.append(m.text))
                    pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
                    pg.goto(f"{a.url}?lib={lib}&board={board}&fs={fs}" + (f"&off={off}" if off else "") + ("&paths=1" if a.bright else ""))
                    pg.wait_for_function("window.__GRADE__ && window.__GRADE__()", timeout=60000)
                    pg.wait_for_timeout(2500)
                    g = pg.evaluate("window.__GRADE__()")
                    rows.append({"vp": vp, **g, "errors": errs})
                    if a.shots:
                        pg.screenshot(path=f"{a.shots}/{lib}-{key}-{vp}-fs{fs}.png")
                    pg.close()
    b.close()
if a.json:
    a.json.write_text(json.dumps(rows))
for r in rows:
    print(
        f"{r['vp']:>9} fs{r['fs']} {r['lib']:<8} {r['board']:<20} canvas {r['canvas']['w']:.0f}x{r['canvas']['h']:.0f} box {r['box']['w']:.0f}x{r['box']['h']:.0f} sun {r['sun']:5.1f} px"
        f"  joined {r['joined']}/{r['pairs']}  through {r['through']}  over-name {r['named']}  crossing {r['cross']}  out-of-order {r['order']}"
        + (f"  ERRORS {r['errors']}" if r["errors"] else "")
    )
# stability: against the whole demo board, the states left that change side of the Board's middle when one is switched off
for vp in a.vp:
    for lib in a.lib:
        at = {r["board"]: r["side"] for r in rows if r["vp"] == vp and r["lib"] == lib and r["fs"] == int(a.fs[0])}
        if "base" not in at or not all(f"base~{s}" in at for s in STATES):
            continue
        moved = {s: [i for i, side in at[f"base~{s}"].items() if at["base"][i] != side] for s in STATES}
        print(f"{vp:>9} {lib:<8} side changes: " + "; ".join(f"{s} {len(m)}" for s, m in moved.items()) + f"; total {sum(len(m) for m in moved.values())}")
