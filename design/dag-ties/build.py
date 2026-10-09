"""Build the tied-DAGs mockup: the real page, built from source with `dag-ties-src.patch` applied, over a scrubbed capture.

usage: git apply design/dag-ties/dag-ties-src.patch
       pnpm --dir starpulse/web --ignore-workspace run build
       PYTHONPATH=. python design/dag-ties/build.py [--fixture PATH] [--server URL]
       git apply -R design/dag-ties/dag-ties-src.patch

The patch draws the DAGs tied to a Board state back onto the Star Map (`dagTies.ts`): a small DAGs hangar docked beside
each state they act on, with an orbiter for every writer of a transition out of it and every DAG a Board event landing in
it cues, docked by one of six options (`?place=`); a DAG that only launches work stays off the map. mock.js simulates
their runs, with five running glyphs (`?glyph=`). `--fixture` reuses a saved capture, else the server is captured and the capture saved there.
"""

import argparse
import hashlib
import json
import re
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


def scrub_ledgers(snap: dict) -> dict:
    """demo.scrub predates the Ledger (D9): rename the task ids, merge shas, run ids and pull requests it carries."""
    for i, e in enumerate(e for es in snap.get("ledgers", {}).values() for e in es):
        if e.get("pr"):
            e["pr"] = {"repo": "demo", "number": 100 + i, "url": "#"}
    text, ids = json.dumps(snap), {}
    text = re.sub(r"TASK-\d+", lambda m: ids.setdefault(m[0], f"DEMO-{1000 + len(ids)}"), text)
    text = re.sub(r"\b[0-9a-f]{40}\b", lambda m: hashlib.sha1(m[0].encode()).hexdigest(), text)
    text = re.sub(r"-force-\d+", "-force-1", text)
    return json.loads(text)


snap = scrub_ledgers(snap)
html = demo.page(demo.STATIC, snap)
head = (
    "<!--\n  Design mockup of the DAGs tied to a state, back on the Star Map; under operator review, not served by starpulse.\n"
    "  The real page, built from a source copy that draws them (dag-ties-src.patch), over a scrubbed capture, with mock.js\n"
    "  simulating their runs. Variants: ?place=orbit|edge|line|side|rim|label  ?glyph=tail|spin|ripple|breathe|glow  ?sim=live|rest|fail  ?fs=100|125|150\n-->\n"
)
html = html.replace("<head>", "<head>\n" + head, 1).replace("</body>", '<script src="mock.js"></script>\n</body>', 1)
(HERE / "index.html").write_text(html)
print(HERE / "index.html")
