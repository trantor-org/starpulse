"""Build the claim-expiry mockup: the skill-phases page with `claim-expiry-src.patch` on top, over a scrubbed capture.

usage: git checkout bac04795b3a6 -- starpulse/web/src   # the patches' base
       git apply design/skill-phases/skill-phases-src.patch design/claim-expiry/claim-expiry-src.patch
       pnpm --dir starpulse/web --ignore-workspace exec vite build --mode one-file
       PYTHONPATH=. python design/claim-expiry/build.py [--fixture PATH] [--server URL]
       git checkout HEAD -- starpulse/web/src

The patch (TASK-7787) draws where an In Progress task's claim shows on the kanban, beside the skill-phases phase track:
`&claim=a` the footer's assignee chip, `b` a top-row badge, `c` the card's edge, `d` the phase track's age and marker,
`e` the lane header's unheld count as a filter. An unheld card reads the moment, session and last renewal the claim-TTL
sweeper's `Released` event already carries; a held one shows its time left only under ten minutes. `&sim=claim` drains
one claim to expiry in 40 s and `&few=1` keeps three cards a lane.
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


# One character of each name in a class, as ci/public_names.py writes them, so this file does not name a host.
HOSTS = {r"ai-v[m]": "vm", r"unrai[d]": "nas", r"proxmo[x]": "hypervisor", r"\btowe[r]\b": "host"}


def scrub_ledgers(snap: dict) -> dict:
    """demo.scrub predates the Ledger (D9): rename the task ids, merge shas, run ids, pull requests and host names it carries."""
    for i, e in enumerate(e for es in snap.get("ledgers", {}).values() for e in es):
        if e.get("pr"):
            e["pr"] = {"repo": "demo", "number": 100 + i, "url": "#"}
    text, ids = json.dumps(snap), {}
    text = re.sub(r"TASK-\d+", lambda m: ids.setdefault(m[0], f"DEMO-{1000 + len(ids)}"), text)
    text = re.sub(r"\b[0-9a-f]{40}\b", lambda m: hashlib.sha1(m[0].encode()).hexdigest(), text)
    text = re.sub(r"-force-\d+", "-force-1", text)
    for name, neutral in HOSTS.items():  # DAG names carry the operator's host names
        text = re.sub(name, neutral, text, flags=re.IGNORECASE)
    return json.loads(text)


snap = scrub_ledgers(snap)
# the patch's `&sim=2|3` walks two Board tasks it names by id: give two In Progress tasks those ids
board = next(f for f in snap["flows"] if f["name"] == "board")
picked = [a["id"] for a in board["agents"] if a["state"] == "in_progress"][:2]
text = json.dumps(snap)
for old, new in zip(picked, ["DEMO-901", "DEMO-902"]):
    text = re.sub(rf'"{old}"', f'"{new}"', text)
snap = json.loads(text)
html = demo.page(demo.STATIC, snap)
head = (
    "<!--\n  Design mockup of where an expired or unheld claim shows on the kanban; not served by starpulse.\n"
    "  The real page, built from source with skill-phases-src.patch and claim-expiry-src.patch, over a scrubbed capture.\n"
    "  States: ?view=kanban&concept=h&mock=1&sim=2|claim&claim=a|b|c|d|e[&few=1]  (a bare load opens claim=a)\n-->\n"
    '<script>if (!location.search) history.replaceState(null, "", "?view=kanban&concept=h&mock=1&sim=2&claim=a")</script>\n'
)
html = html.replace("<head>", "<head>\n" + head, 1)
(HERE / "index.html").write_text(html)
print(HERE / "index.html")
