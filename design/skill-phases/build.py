"""Build the skill-phases mockup: the real page, built from source with `skill-phases-src.patch` applied, over a scrubbed capture.

usage: git checkout bac04795b3a6 -- starpulse/web/src   # the patch's base
       git apply design/skill-phases/skill-phases-src.patch
       pnpm --dir starpulse/web --ignore-workspace exec vite build --mode one-file
       PYTHONPATH=. python design/skill-phases/build.py [--fixture PATH] [--server URL]
       git checkout HEAD -- starpulse/web/src

The patch draws the phases a task's skill runs in on the Star Map (`transit.ts`): each phase machine a task is in opens as
a branch off the Board state it left, its submachines as rays at right angles off their parent's stations, every task a
dot on its station, stacked out from the sun when two share one; a hover traces the dot's path back through the tree,
fading from one machine's colour into the next. Board DAGs take turns in 12 s windows. The kanban card names the phase
and step. `?mock=1` puts the In Progress tasks in phases, `&sim=2` walks two tasks through six machines and `&sim=3`
stacks them, a step every 4 s. `--fixture` reuses a saved capture, else the server is captured and the capture saved there.
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
# the patch's `&sim=2|3` walks two Board tasks it names by id: give two In Progress tasks those ids
board = next(f for f in snap["flows"] if f["name"] == "board")
picked = [a["id"] for a in board["agents"] if a["state"] == "in_progress"][:2]
text = json.dumps(snap)
for old, new in zip(picked, ["TASK-7605", "TASK-7639"]):
    text = re.sub(rf'"{old}"', f'"{new}"', text)
snap = json.loads(text)
html = demo.page(demo.STATIC, snap)
head = (
    "<!--\n  Design mockup of skill phases on the Star Map and kanban; approved by the operator, not served by starpulse.\n"
    "  The real page, built from a source copy that draws them (skill-phases-src.patch), over a scrubbed capture.\n"
    "  States: ?view=starmap|kanban&concept=h&mock=1&sim=2|3  (a bare load opens the star map at sim=2)\n-->\n"
    '<script>if (!location.search) history.replaceState(null, "", "?view=starmap&concept=h&mock=1&sim=2")</script>\n'
)
html = html.replace("<head>", "<head>\n" + head, 1)
(HERE / "index.html").write_text(html)
print(HERE / "index.html")
