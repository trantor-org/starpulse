"""Build the phone-width mockup: the real page, built from source with `phone-src.patch` applied, over a scrubbed capture.

usage: git apply design/phone/phone-src.patch
       pnpm --dir starpulse/web --ignore-workspace run build
       PYTHONPATH=. python design/phone/build.py [--fixture PATH] [--server URL]
       git apply -R design/phone/phone-src.patch

The patch adds the phone navigator (a view bar along the bottom edge, or a corner button, each opening the real navigator as a
sheet), the Kanban's one-lane layout (a lane strip, or stacked lane headers), the DAGs' two-line rows and the Admin's stacked rows,
every rule inside the page's 900 px collapse and behind a switch on `<html>` that mock.js sets. Without the switches the page draws
as today, so one build serves both sides of the comparison. `--fixture` reuses a saved capture, else the server is captured and the
capture saved there.
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
    "<!--\n  Design mockup of the page at phone width (390x844), under operator review; not served by starpulse.\n"
    "  The real page, built from a source copy that adds the phone navigator and the Kanban, DAGs and Admin phone layouts\n"
    "  (phone-src.patch), over a scrubbed capture, with mock.js layered on. Variants: ?view=constellation|kanban|dags|admin\n"
    "  ?nav=bar|drawer|overlay  ?kb=tabs|stack  ?fs=100|125|150  ?lane=<lane id>  ?s=sheet|task|dag  ?frame=1&phone=on|current\n-->\n"
)
html = html.replace("<head>", "<head>\n" + head, 1).replace("</body>", '<script src="mock.js"></script>\n</body>', 1)
(HERE / "index.html").write_text(html)
print(HERE / "index.html")
