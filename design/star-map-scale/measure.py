"""Measure the Star Map Board's on-screen sizes at each viewport through window.flowProbe(), today's sizing beside the grid proposal.

usage: python design/star-map-scale/measure.py http://localhost:PORT/star-map-scale/index.html [--shots DIR]

Needs Playwright and a system Chrome. Prints one row per viewport and sizing: canvas, fit zoom k, sun px (SUN_R * k), the footprint R
range across states in px, and any console error. A phone viewport runs with rails=off (the rails leave it no canvas today).
"""

import argparse
import json

from playwright.sync_api import sync_playwright

SUN_R = 34
VPS = [(390, 844), (1366, 768), (1600, 1000), (1920, 1080), (2560, 1440), (3440, 1440), (3840, 2160)]
ap = argparse.ArgumentParser()
ap.add_argument("url")
ap.add_argument("--shots")
ap.add_argument("--fs", default="100")
a = ap.parse_args()
out = []
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    for w, h in VPS:
        for sizing in ("current", "grid"):
            pg = b.new_page(viewport={"width": w, "height": h})
            errs = []
            pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            rails = "&rails=off" if w < 700 else ""
            pg.goto(f"{a.url}?frame=1&sizing={sizing}&fs={a.fs}{rails}")
            pg.wait_for_function("window.flowProbe && window.flowProbe().ready && window.flowProbe().states.length", timeout=60000)
            pg.wait_for_timeout(3000)
            pr = pg.evaluate("window.flowProbe()")
            k, rs = pr["fit"], sorted(s["r"] for s in pr["states"])
            out.append({"vp": f"{w}x{h}", "sizing": sizing, "canvas": f"{pr['canvas']['w']:.0f}x{pr['canvas']['h']:.0f}", "k": round(k, 3),
                        "sunPx": round(SUN_R * k, 1), "R": f"{rs[0]:.1f}-{rs[-1]:.1f}", "errors": errs})
            if a.shots:
                pg.screenshot(path=f"{a.shots}/{sizing}-{w}x{h}-fs{a.fs}.png")
            pg.close()
    b.close()
for r in out:
    print(json.dumps(r))
