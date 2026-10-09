"""Build the UI-polish mockup: the real page, built from this branch with `ui-polish-src.patch` applied, over the demo capture.

usage: git apply design/ui-polish/ui-polish-src.patch
       pnpm --dir starpulse/web --ignore-workspace run build
       PYTHONPATH=. python design/ui-polish/build.py --fixture PATH
       git apply -R design/ui-polish/ui-polish-src.patch

The patch lets mock.js answer a demo page's /api routes (`window.__MOCK_API__`), so the start question shows its harness picks,
which a demo page, with no session-start service, never does. `--fixture` is a saved capture (the PR demo's `__FLOW_FIXTURE__`),
else the server is captured, scrubbed and saved there.
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
    "<!--\n  Design mockup of the Kanban, DAGs and start-question UI polish, under operator review; not served by starpulse.\n"
    "  The real page, built from the branch with ui-polish-src.patch, over the demo capture, with mock.js layered on.\n"
    "  Variants: ?view=kanban|dags|constellation  ?s=stack|start  ?harness=two|one|none  ?apply=run|done|fail  ?fs=100|125|150\n-->\n"
)
html = html.replace("<head>", "<head>\n" + head, 1).replace("</body>", '<script src="mock.js"></script>\n</body>', 1)
(HERE / "index.html").write_text(html)
print(HERE / "index.html")
