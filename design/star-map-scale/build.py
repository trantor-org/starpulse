"""Build the Star Map sizing mockup: the real page, built from source with `star-map-scale-src.patch` applied, over a scrubbed capture.

usage: git apply design/star-map-scale/star-map-scale-src.patch
       pnpm --dir starpulse/web --ignore-workspace run build
       PYTHONPATH=. python design/star-map-scale/build.py [--fixture PATH] [--server URL]
       git apply -R design/star-map-scale/star-map-scale-src.patch

The patch adds a spread sizing rule for the Board (`window.__SIZING__`, set by mock.js): the same rings, moons and sub-state chains,
the states spread out from the canvas's centre to fill it, staggered or stretched, each with a fixed footprint or one sized by its load,
the zoom the largest at which no two footprints meet, labels scaled with the sun. Without it the page draws as today, so one build serves both
sides of the comparison. `--fixture` reuses a saved capture, else the server is captured and the capture saved there.
`measure.py` samples today's sizes per viewport (the table in TASK-3747).
"""

import argparse
import json
from pathlib import Path

from starpulse._internal.cli import demo

HERE = Path(__file__).parent
ap = argparse.ArgumentParser()
ap.add_argument("--fixture", type=Path)
ap.add_argument("--server", default="http://127.0.0.1:8766")
a = ap.parse_args()
if a.fixture and a.fixture.exists():
    snap = json.loads(a.fixture.read_text())
else:
    snap = demo.scrub(demo.capture(a.server))
    snap["claims"] = {}  # demo.scrub keeps claim reasons, which name real tasks
    if a.fixture:
        a.fixture.write_text(json.dumps(snap))
html = demo.page(demo.STATIC, snap)
head = (
    "<!--\n  Design mockup of the Star Map's size per screen resolution, under operator review; not served by starpulse.\n"
    "  The real page, built from a source copy that adds a spread sizing rule (star-map-scale-src.patch), over a scrubbed capture, with\n"
    "  mock.js layered on. Variants: ?res=WxH  ?fs=100|125|150  ?arr=stagger|stretch  ?foot=fixed|load  ?frame=1&sizing=current|spread&rails=off\n-->\n"
)
html = html.replace("<head>", "<head>\n" + head, 1).replace("</body>", '<script src="mock.js"></script>\n</body>', 1)
(HERE / "index.html").write_text(html)
print(HERE / "index.html")
