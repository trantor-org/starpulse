"""Build the Star Map layout mockup: the real page, built from source with `star-map-layout-src.patch` applied, over a scrubbed capture.

usage: pnpm --dir design/star-map-layout --ignore-workspace install
       node design/star-map-layout/layouts.mjs --write
       git apply design/star-map-layout/star-map-layout-src.patch
       pnpm --dir starpulse/web --ignore-workspace run build
       PYTHONPATH=. python design/star-map-layout/build.py [--fixture PATH] [--server URL]
       git apply -R design/star-map-layout/star-map-layout-src.patch

The patch lets a script hand the Board its states' places and its paths (`window.__LAYOUT__`, set by mock.js), has the Board redraw
each such path as one smooth curve that goes no further over a name or into a state than the library's own line, and adds each path and
name to the page's probe; without that script the page draws as shipped, so one build serves the shipped Board and every library.
`layouts.mjs` runs the four libraries (dagre, Graphviz dot, ELK Layered, WebCola) over each board in shared.js and writes layouts.js;
the page reads those layouts and never loads a library, since two of the four bundles do not pass the public demo's scan.
`--fixture` reuses a saved capture, else the server is captured and the capture saved there. `measure.py` reads every library and
board off the built page.
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
    "<!--\n  Design mockup of the Star Map Board laid out by a layout library, under operator review; not served by starpulse.\n"
    "  The real page, built from a source copy that takes its states' places and paths from a script (star-map-layout-src.patch), over\n"
    "  a scrubbed capture, with shared.js (the boards), layouts.js (each library's layouts, from layouts.mjs) and mock.js layered on.\n"
    "  Variants: ?lib=shipped|dagre|graphviz|elk|cola  ?board=base|third-in-tier|two-more-tiers|fourteen|unlisted|three  ?off=<state>  ?fs=100|125|150\n-->\n"
)
scripts = "".join(f'<script src="{name}"></script>\n' for name in ("shared.js", "layouts.js", "mock.js"))
html = html.replace("<head>", "<head>\n" + head, 1).replace("</body>", scripts + "</body>", 1)
(HERE / "index.html").write_text(html)
print(HERE / "index.html")
