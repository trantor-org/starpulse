"""Build the DAGs-view mockup: the real page, built from source with `dags-view-src.patch` applied, over a scrubbed capture.

usage: git apply design/dags-view/dags-view-src.patch
       pnpm --dir starpulse/web --ignore-workspace run build
       PYTHONPATH=. python design/dags-view/build.py [--fixture PATH] [--server URL]
       git apply -R design/dags-view/dags-view-src.patch

The patch adds a DAGs view beside the Kanban (`Dags.tsx`, its CSS, a Views button and its legend) and hides the navigator's
DAGs list and Queues on the Star Map when the capture carries no DAGs, as mock.js's `?map=bare` leaves it. `--fixture` reuses a saved capture, else the server is captured and
the capture saved there.
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
    "<!--\n  Design mockup of a DAGs view beside the Kanban, under operator review; not served by starpulse.\n"
    "  The real page, built from a source copy that adds the view (dags-view-src.patch), over a scrubbed capture, with mock.js\n"
    "  layered on. Variants: ?map=bare|today  ?safe=demo|live  ?n=150|400  ?fs=100|125|150\n-->\n"
)
html = html.replace("<head>", "<head>\n" + head, 1).replace("</body>", '<script src="mock.js"></script>\n</body>', 1)
(HERE / "index.html").write_text(html)
print(HERE / "index.html")
