"""Build the DAG-constellations mockup: the real page, built from source with `dag-only-src.patch` applied, over a scrubbed capture.

usage: git apply design/dag-constellations/dag-only-src.patch
       pnpm --dir starpulse/web --ignore-workspace run build
       PYTHONPATH=. python design/dag-constellations/build.py [--fixture PATH] [--server URL]
       git apply -R design/dag-constellations/dag-only-src.patch

The patch changes only the DAGs: how a DAG is drawn (`glyph`, `quietStar`), where a DAG with no Board tie sits (`skyDags`,
`drawMarks`) and the navigator without its DAGS list. `--fixture` reuses a saved capture, else the server is captured and
the capture saved there.
"""

import argparse
import json
from pathlib import Path

from starpulse import demo

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
    "<!--\n  Design mockup of DAGs as constellations, under operator review; not served by starpulse.\n"
    "  The real page, built from a source copy that changes only the DAGs (dag-only-src.patch), over a scrubbed capture,\n"
    "  with mock.js layered on. Variants: ?glyph=quiet|radiant|live  ?free=sky|marks|live  ?n=150|400  ?fs=100|125|150\n-->\n"
)
html = html.replace("<head>", "<head>\n" + head, 1).replace("</body>", '<script src="mock.js"></script>\n</body>', 1)
(HERE / "index.html").write_text(html)
print(HERE / "index.html")
