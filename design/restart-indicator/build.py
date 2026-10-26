"""Build the restart-indicator mockup: the real page, built from this branch with `restart-indicator-src.patch` applied, over the demo capture.

usage: git apply design/restart-indicator/restart-indicator-src.patch
       pnpm --dir starpulse/web --ignore-workspace run build
       PYTHONPATH=. python design/restart-indicator/build.py --fixture PATH
       git apply -R design/restart-indicator/restart-indicator-src.patch

The patch gives the status dot its reconnecting state and the stats line a connection note, and hands a demo page's HUD to mock.js
(`window.__MOCK_HUD__`), which plays the restart, the new build and the drop. `--fixture` is a saved capture (the PR demo's
`__FLOW_FIXTURE__`), else the server is captured, scrubbed and saved there.
"""

import argparse
import json
from pathlib import Path

from starpulse.cli import demo

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
    "<!--\n  Design mockup of the restart-aware status indicator, under operator review; not served by starpulse.\n"
    "  The real page, built from the branch with restart-indicator-src.patch, over the demo capture, with mock.js layered on.\n"
    "  Variants: ?s=live|restart|update|drop|wait|off|new  ?view=kanban|dags|constellation  ?fs=100|125|150\n-->\n"
)
html = html.replace("<head>", "<head>\n" + head, 1).replace("</body>", '<script src="mock.js"></script>\n</body>', 1)
(HERE / "index.html").write_text(html)
print(HERE / "index.html")
