"""Build the state-type display mockup (in design/column-labels/): the real page, built from this branch with `column-labels-src.patch` applied, over the demo capture.

usage: git apply design/column-labels/column-labels-src.patch
       pnpm --dir starpulse/web --ignore-workspace run build
       PYTHONPATH=. python design/column-labels/build.py --fixture PATH
       git apply -R design/column-labels/column-labels-src.patch

The patch puts a glyph for each column state's declared type (initial, resting, waiting_on_fact, waiting_on_person, final) in its header, named on hover; columns keep the machine's names and
order. mock.js adds the review bar (view and text size). The capture's board machine gets the seeded types on its states (as `role`), the field the API
slice adds. `--fixture` is a saved capture (the PR demo's `__FLOW_FIXTURE__`), else the server is captured, scrubbed and saved there.
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
board = next(f for f in snap["flows"] if f["name"] == "board")
for state in board["machine"]["states"]:
    state["role"] = demo.SEED_ROLES.roles.get(state["id"])
html = demo.page(demo.STATIC, snap)
head = (
    "<!--\n  Design mockup of state-type display, under operator review; not served by starpulse.\n"
    "  The real page, built from the branch with column-labels-src.patch, over the demo capture, with mock.js layered on.\n"
    "  Each header glyph is its state's declared type; two states may share one (Waiting and Review both wait on a fact).\n"
    "  Variants: ?view=kanban|constellation  ?fs=100|125|150\n-->\n"
)
html = html.replace("<head>", "<head>\n" + head, 1).replace("</body>", '<script src="mock.js"></script>\n</body>', 1)
(HERE / "index.html").write_text(html)
print(HERE / "index.html")
