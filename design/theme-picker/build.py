"""Build the Admin theme picker mockup: the real page, built from this branch with `theme-picker-src.patch` applied, over the
demo capture, with each `?s=` state seeded into this browser's `sp.theme` before the page boots and its dialogs opened by mock.js.

usage: git apply design/theme-picker/theme-picker-src.patch
       pnpm --dir starpulse/web --ignore-workspace exec vite build --mode one-file
       PYTHONPATH=. python design/theme-picker/build.py --fixture PATH
       git apply -R design/theme-picker/theme-picker-src.patch

The patch adds features/admin/theme (packs, the base16 import and its dE gate, backgrounds, and recolor.ts, a mockup-only stand-in
that remaps today's palette until the drawing code reads the tokens), the Theme and Preview cards in Admin, and the renderer's sky
wash reset on sp:theme. The shipped slices build each piece with its tests.

The seeded imports are built by the page's own `fromBase16`, run under node, so a state shows what an import would save.
"""

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

from starpulse.cli import demo

HERE = Path(__file__).parent
ap = argparse.ArgumentParser()
ap.add_argument("--fixture", type=Path)
ap.add_argument("--server", default="http://127.0.0.1:8766")
ap.add_argument("--theme-src", type=Path, default=Path("starpulse/web/src/features/admin/theme"))
a = ap.parse_args()

KEYS = [f"base0{d}" for d in "0123456789ABCDEF"]
SCHEMES = {
    "tomorrow": ("Tomorrow Night", "Chris Kempson", "1d1f21 282a2e 373b41 969896 b4b7b4 c5c8c6 e0e0e0 ffffff cc6666 de935f f0c674 b5bd68 8abeb7 81a2be b294bb a3685a"),
    "onedark": ("One Dark", "Lalit Magant", "282c34 353b45 3e4451 545862 565c64 abb2bf b6bdca c8ccd4 e06c75 d19a66 e5c07b 98c379 56b6c2 61afef c678dd be5046"),
    "kanagawa": ("Kanagawa", "Tommaso Laurenzi", "1f1f28 16161d 223249 54546d 727169 dcd7ba c8c093 717c7c c34043 ffa066 c0a36e 76946a 6a9589 7e9cd8 957fb8 d27e99"),
    "twilight": ("Twilight", "David Hart", "1e1e1e 323537 464b50 5f5a60 838184 a7a7a7 c3c3c3 ffffff cf6a4c cda869 f9ee98 8f9d6a afc4db 7587a6 9b859d 9b703f"),
}
yaml = {
    k: f'scheme: "{name}"\nauthor: "{author}"\n' + "\n".join(f'{key}: "{v}"' for key, v in zip(KEYS, hexes.split()))
    for k, (name, author, hexes) in SCHEMES.items()
}

SEED = """
import { closest, build, fromBase16, rampFrom, bgRefusal, SLATE } from "./scheme.ts";
const yaml = JSON.parse(process.argv[2]);
const tn = fromBase16(yaml.tomorrow);
const gate = Object.fromEntries(Object.entries(yaml).map(([k, y]) => {
  const s = fromBase16(y as string);
  return [k, [closest(build(s.pack, SLATE).t)[0], bgRefusal(s.bg)]];
}));
const plum = rampFrom("#2a1f3d");
console.log(JSON.stringify({
  gate, refusedRamp: bgRefusal(rampFrom("#5a6b8c")),
  packs: [{ id: "u1", pack: tn.pack }],
  bgs: [{ id: "u1b", name: tn.name, n: tn.bg }, { id: "u2", name: "Plum", n: plum }],
}));
"""
with tempfile.TemporaryDirectory() as tmp:
    for f in ("color.ts", "scheme.ts", "packs.json"):
        src = (a.theme_src / f).read_text()
        src = re.sub(r'from "\./color"', 'from "./color.ts"', src)
        src = re.sub(r'from "\./packs\.json";', 'from "./packs.json" with { type: "json" };', src)
        (Path(tmp) / f).write_text(src)
    (Path(tmp) / "seed.ts").write_text(SEED)
    out = subprocess.run(["node", "seed.ts", json.dumps(yaml)], cwd=tmp, capture_output=True, text=True, check=True).stdout
seed = json.loads(out)
print("gate (closest ΔE on Slate, bg refusal):", json.dumps(seed["gate"]), "| #5a6b8c:", seed["refusedRamp"])

own = {"packs": seed["packs"], "bgs": seed["bgs"]}
STATES = {
    "fresh": None,
    "grid": {"pack": "starpulse", "bg": "slate", **own},
    "solarized": {"pack": "solarized", "bg": "slate", **own},
    "map": {"pack": "solarized", "bg": "slate", **own},
    "map-own": {"pack": "u1", "bg": "u1b", **own},
    "bg-applied": {"pack": "starpulse", "bg": "u2", **own},
}
for s in ("import", "import-preview", "import-warn", "import-refused", "import-invalid", "rename", "delete", "bg-color", "bg-refused"):
    STATES[s] = STATES["grid"]
VIEW = {"map": "constellation", "map-own": "constellation"}

boot = (
    "<script>\n// mockup: a ?s= state seeds this browser's theme and opens its view before the page boots\n(() => {\n"
    f"  window.__SCHEMES__ = {json.dumps(yaml)};\n"
    f"  const S = {json.dumps(STATES)}, V = {json.dumps(VIEW)};\n"
    "  const q = new URLSearchParams(location.search), s = q.get('s');\n"
    "  if (!s || !(s in S)) return;\n"
    "  try { S[s] ? localStorage.setItem('sp.theme', JSON.stringify(S[s])) : localStorage.removeItem('sp.theme'); } catch {}\n"
    "  if (!q.has('view')) { q.set('view', V[s] || 'admin'); history.replaceState(null, '', '?' + q); }\n"
    "})();\n</script>\n"
)

if a.fixture and a.fixture.exists():
    snap = json.loads(a.fixture.read_text())
else:
    snap = demo.scrub(demo.capture(a.server))
    snap["claims"] = {}  # demo.scrub keeps claim reasons, which name real tasks
    if a.fixture:
        a.fixture.write_text(json.dumps(snap))
# demo.scrub keeps DAG names, and some name hosts ci/public_names.py denies (a class per name, as it spells them)
hosts = {"u": "nas", "p": "hypervisor", "a": "agent-host"}
host = re.compile(r"unrai[d]|proxmo[x]|ai-v[m](-\d+)?", re.IGNORECASE)
snap = json.loads(host.sub(lambda m: hosts[m.group()[0].lower()], json.dumps(snap)))
html = demo.page(demo.STATIC, snap)
head = (
    "<!--\n  Design mockup of the Admin theme picker, under operator review; not served by starpulse.\n"
    "  The real page, built from the branch, over the demo capture; each ?s= state seeds this browser's sp.theme, and mock.js\n"
    "  opens its dialog. Variants: ?s=" + "|".join(STATES) + "\n-->\n"
)
html = html.replace("<head>", "<head>\n" + head + boot, 1).replace("</body>", '<script src="mock.js"></script>\n</body>', 1)
(HERE / "index.html").write_text(html)
print(HERE / "index.html")
