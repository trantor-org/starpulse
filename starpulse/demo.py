"""Build StarPulse as one self-contained HTML file that runs with no server.

    .venv/bin/python -m starpulse.demo --server http://127.0.0.1:8766 --out .tmp/flow-demo.html
    .venv/bin/python -m starpulse.demo --mockup <the design mockup directory> --out .tmp/mockup-demo.html

It reads a running starpulse.server's snapshot for its structure (the
machines, the DAGs and their steps) and replaces every task with a synthetic
one in the same state, so no task text, PR or address leaves. The
built page in `static/` is inlined around the result, which the page reads as
`window.__FLOW_FIXTURE__` and animates as `?demo` does. `--mockup` does the same
for a design mockup's saved `data.js`, keeping each session's link to its task.
"""

import argparse
import collections
import itertools
import json
import re
import urllib.request
from pathlib import Path

STATIC = Path(__file__).parent / "static"
#: Board labels that say what kind of work a task is and nothing about it.
LABELS = re.compile(r"^(kind-[a-z]+|size-\d+|agent-resolvable|needs-human|adr-needed|bug|feature)$")
#: The mockup data keys `scrub_mockup` knows how to clean; any other key is refused rather than passed through.
MOCKUP_KEYS = {"now", "dags", "writers", "launches", "cues", "domains", "descriptions", "flows"}
TITLES = [
    "Add retry budget to the ingest worker",
    "Tighten the nightly backup window",
    "Document the cache eviction policy",
    "Split the metrics exporter by host",
    "Migrate the job runner to the new queue",
    "Trim unused dashboard panels",
    "Alert on certificate expiry",
    "Cut cold-start time of the API",
]


def capture(server: str) -> dict:
    """The snapshot the server's event stream opens with."""
    with urllib.request.urlopen(f"{server}/api/events", timeout=30) as stream:
        for line in stream:
            if line.startswith(b"data: "):  # the first event on a connect is the snapshot
                return json.loads(line.removeprefix(b"data: "))
    raise ValueError(f"{server}/api/events sent no snapshot")


#: A Board for a capture that has none (CI's server has no tasks), so the Kanban demo is not an empty page. It is
#: scrubbed like a live Board: (state, milestone, labels, index of the task it depends on, profile, pull request).
SEED = [
    ("ready", "m-2", ["size-2", "kind-feature"], None, "@agent-fast-low", None),
    ("ready", "m-2", ["size-3"], None, "", None),
    ("ready", "", ["kind-bug"], None, "@agent-standard-high", None),
    ("waiting", "m-2", ["size-5", "needs-human"], 0, "", None),
    ("waiting", "m-1", ["size-3"], 4, "@agent-standard-high", None),
    ("in_progress", "m-2", ["size-5", "kind-feature"], None, "@agent-deep-high", ("pending", False, 0)),
    ("in_progress", "m-1", ["size-2"], None, "@agent-standard-high", None),
    ("in_progress", "", ["kind-bug"], None, "@agent-fast-low", ("failing", False, 0)),
    ("review", "m-2", ["size-3", "kind-feature"], None, "@agent-standard-high", ("pass", False, 2)),
    ("review", "m-1", ["size-1"], None, "@agent-fast-low", ("pass", False, 0)),
    ("needs_attention", "m-1", ["size-5", "needs-human"], None, "", ("failing", False, 1)),
    ("done", "m-2", ["size-2"], None, "@agent-fast-low", ("pass", True, 0)),
    ("done", "m-1", ["size-3", "kind-feature"], None, "@agent-deep-high", ("pass", True, 0)),
    ("done", "", ["size-1"], None, "@agent-standard-high", ("pass", True, 0)),
]


def _seed() -> tuple[list[dict], dict]:
    """`SEED` as a live Board's tasks and the pull requests the server would have read for them."""
    ids = [f"seed-{i}" for i in range(len(SEED))]
    agents, pulls = [], {}
    for i, (state, milestone, labels, after, model, pull) in enumerate(SEED):
        agents.append(
            {"id": ids[i], "state": state, "model": model, "milestone": milestone, "labels": labels}
            | ({"dependencies": [ids[after]]} if after is not None else {})
        )
        if pull:
            checks, merged, threads = pull
            pulls[ids[i]] = [{"checks": checks, "merged": merged, "threads": threads}]
    return agents, pulls


def scrub(live: dict) -> dict:
    """`live` with its structure kept and every task, settled task, run id and address replaced.

    A task keeps one demo name wherever it is drawn, so a machine's task still sits on the Board. A Board task keeps
    its lane, its milestone (renamed `m-N`), its kind and size labels, the dependencies that are on the Board and a
    synthetic description; its pull requests keep their checks and threads but lose their number and address.
    """
    names: dict[str, str] = {}
    board = [a for f in live["flows"] if f["name"] == "board" for a in f["agents"]]
    pulls = live.get("pulls", {})
    if not board:
        board, pulls = _seed()
    for a in board:  # the Board's tasks are DEMO-1.. in Board order, whichever flow comes first
        names.setdefault(a["id"], f"DEMO-{len(names) + 1}")
    keys = sorted({a["milestone"] for a in board if a.get("milestone")}, key=lambda k: (len(k), k))
    milestones = {k: f"m-{i + 1}" for i, k in enumerate(keys)}

    def task(a: dict, *, is_board: bool) -> dict:
        name = names.setdefault(a["id"], f"DEMO-{len(names) + 1}")
        demo = _task(int(name.removeprefix("DEMO-")) - 1, a)
        if is_board:
            return demo | {
                "milestone": milestones.get(a.get("milestone"), ""),
                "labels": [x for x in a.get("labels", []) if LABELS.match(x)],
                "dependencies": [names[d] for d in a.get("dependencies", []) if d in names],
                "description": f"Synthetic demo task: {demo['title'].lower()}.",
            }
        keep = {k: a[k] for k in ("state", "model", "steps", "trail", "active") if k in a}
        return {**keep, "id": demo["id"], "title": demo["title"], "task": demo["id"]}

    flows = [
        {
            **f,
            "agents": [
                task(a, is_board=f["name"] == "board") for a in (board if f["name"] == "board" else f["agents"])
            ],
        }
        for f in live["flows"]
    ]
    _seed_delivery(flows, live["now"])
    return {
        **live,
        "boardUrl": None,
        "hint": None,
        "domains": [{**d, "dags": [{"name": x["name"], "runSafe": False} for x in d["dags"]]} for d in live["domains"]],
        "dags": [{**d, "runId": f"demo-{i}"} for i, d in enumerate(live["dags"])],
        "flows": flows,
        "pulls": {
            names[t]: [
                p | {"number": 100 + int(names[t].removeprefix("DEMO-")) - 1, "url": "#", "stale": False} for p in ps
            ]
            for t, ps in pulls.items()
            if t in names and ps
        },
        "settled": {},
        "error": None,
        "history": _history(flows, live["now"]),
    }


#: The seconds between two synthetic steps of a task's path, before each task's own spread.
STEP_S = 3 * 3600


def _route(machine: dict, state: str, start: str | None = None) -> list[tuple[str, str, str]]:
    """The shortest (source, event, target) path from the machine's initial state, or `start`, to `state`; [] when
    `state` is out of reach."""
    start = start or next((s["id"] for s in machine["states"] if s.get("initial")), state)
    back: dict[str, tuple[str, str, str] | None] = {start: None}
    queue = collections.deque([start])
    while queue and state not in back:
        here = queue.popleft()
        for t in machine["transitions"]:
            if t["source"] == here and t["target"] not in back:
                back[t["target"]] = (here, t["event"], t["target"])
                queue.append(t["target"])
    path, at = [], state
    while step := back.get(at):
        path.append(step)
        at = step[0]
    return path[::-1]


def _times(n: int, i: int, now: float) -> list[float]:
    """`n` step times ending before `now`, oldest first, spread per task `i` so no two paths line up."""
    gap = STEP_S + 1800 * i
    return [now - gap * (n - k) - 600 * i for k in range(n)]


def _send_back(machine: dict, steps: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """`steps` with one move back: at the last state that has a transition to a state the route already passed, that
    move and the shortest route on to where it was. `steps` unchanged when no state has one."""
    for k, (_, _, here) in reversed(list(enumerate(steps))):
        passed = {s for s, _, _ in steps[: k + 1]} - {here}  # pragma: no mutate: the next source is `here`
        for t in machine["transitions"]:
            if t["source"] == here and t["target"] in passed:
                again = _route(machine, here, start=t["target"])
                return [*steps[: k + 1], (here, t["event"], t["target"]), *again, *steps[k + 1 :]]
    return steps


def _walk(machine: dict, state: str, i: int, now: float, via: str | None = None, back: bool = False) -> list[dict]:
    """Task `i`'s synthetic trail to `state`, on `_times`: the machine's shortest route, through `via` when `via` is
    on the way, sent back once on the way when `back` is set."""
    steps = _route(machine, state)
    if via:
        head, tail = _route(machine, via), _route(machine, state, start=via)
        if head and tail:
            steps = head + tail
    if back:
        steps = _send_back(machine, steps)
    return [{"state": t, "event": e, "at": at} for (_, e, t), at in zip(steps, _times(len(steps), i, now))]


def _seed_delivery(flows: list[dict], now: float) -> None:
    """Place each In Progress Board task on the Board's delivery machine when the capture placed none there, at a varied
    state along that machine, so its level and its back-trace have a task to show."""
    board = next(f for f in flows if f["name"] == "board")
    sub = next(iter(board["machine"].get("subflows", [])), None)
    if sub is None:
        return
    flow = next((f for f in flows if f["name"] == sub["flow"]), None)
    if not flow or flow["agents"]:
        return
    m = flow["machine"]
    # the states a task can be in mid-flow: reachable from the start (the start itself has an empty route), not final
    inner = [s["id"] for s in m["states"] if not s.get("final") and _route(m, s["id"])]
    if not inner:
        return
    for i, a in enumerate(x for x in board["agents"] if x["state"] == sub["state"]):
        state = inner[i % len(inner)]
        trail = _walk(m, state, i, now)
        flow["agents"].append(
            {
                "id": a["id"],
                "title": a["title"],
                "task": a["id"],
                "state": state,
                "model": a["model"],
                "steps": len(trail),
                "trail": trail,
                "active": trail[-1]["at"],
            }
        )


def _history(flows: list[dict], now: float) -> dict[str, list[dict]]:
    """Each Board task's lane changes as `/api/history?task=` answers them: the Board machine's shortest route to its
    lane, on synthetic times, with every second task sent back a lane once so the demo's traces draw backtracks. A machine task's path is its own trail, which the page reads from the snapshot."""
    board = next(f for f in flows if f["name"] == "board")
    line = board["machine"].get("mainLine", [])
    # through the Board's first working lane rather than a creation shortcut, so a path has the hops a real task's has
    via = line[1] if line[1:] else None
    history = {}
    for i, a in enumerate(board["agents"]):
        trail = _walk(board["machine"], a["state"], i, now, via=via, back=i % 2 == 1)
        history[a["id"]] = [
            {"at": s["at"], "from": trail[k - 1]["state"] if k else None, "to": s["state"]} for k, s in enumerate(trail)
        ]
    return history


def _task(i: int, a: dict) -> dict:
    return {"id": f"DEMO-{i + 1}", "title": TITLES[i % len(TITLES)], "state": a["state"], "model": a.get("model", "")}


def _renames(snap: dict) -> dict[str, str]:
    """Each Board task id in a mockup snapshot to the `DEMO-N` name it is shown under."""
    return {a["id"]: f"DEMO-{i + 1}" for i, a in enumerate(snap["flows"]["board"]["agents"])}


def scrub_mockup(snap: dict) -> dict:
    """A design mockup's `window.SNAP` with every task and session renamed, consistently, so links survive."""
    if unknown := set(snap) - MOCKUP_KEYS:
        raise ValueError(f"mockup data has keys the scrub does not know: {sorted(unknown)}")
    tasks = _renames(snap)
    sessions = itertools.count(1)

    def task(i: int, a: dict) -> dict:
        labels = [x for x in a.get("labels", []) if LABELS.match(x)]
        return {**_task(i, a), "labels": labels, "dependencies": [], "prs": []}

    def session(a: dict) -> dict:
        n = next(sessions)
        return {
            "id": f"{n:08x}-0000-4000-8000-000000000000",
            "title": f"demo session {n}",
            "model": a.get("model", ""),
            "kind": a.get("kind", ""),
            "badges": [],
            "task": tasks.get(str(a.get("task"))),
            "active": a.get("active"),
            "state": a["state"],
            "steps": a.get("steps", 0),
            "trail": [{k: t[k] for k in ("state", "event", "at") if k in t} for t in a.get("trail", [])],
        }

    flows = {
        name: {
            **f,
            "agents": [task(i, a) for i, a in enumerate(f["agents"])]
            if name == "board"
            else [session(a) for a in f["agents"]],
        }
        for name, f in snap["flows"].items()
    }
    board = flows["board"]["agents"]
    domains = [
        {**d, "dags": [{"name": x["name"], "runSafe": False} for x in d["dags"]]} for d in snap.get("domains", [])
    ]
    return {
        **snap,
        **({"domains": domains} if "domains" in snap else {}),
        "dags": [{**d, "runId": f"demo-{i}"} for i, d in enumerate(snap["dags"])],
        "descriptions": {t["id"]: f"Synthetic demo task: {t['title'].lower()}." for t in board},
        "flows": flows,
    }


def mockup(design: Path) -> str:
    """`design/index.html` with every local script inlined: `data.js` scrubbed, `history.js` (lane changes keyed by
    task id) renamed like the Board with tasks off it dropped, and any other script as it is."""
    text = (design / "data.js").read_text()
    snap = json.loads(text[text.index("{") : text.rindex("}") + 1])
    renames = _renames(snap)

    def body(name: str) -> str:
        if name == "data.js":
            return "window.SNAP = " + json.dumps(scrub_mockup(snap)).replace("</", "<\\/") + ";"
        src = (design / name).read_text()
        if name == "history.js":
            hist = json.loads(src[src.index("{") : src.rindex("}") + 1])
            return "window.HIST = " + json.dumps({renames[k]: v for k, v in hist.items() if k in renames}) + ";"
        return src.replace("</script", "<\\/script")

    html = (design / "index.html").read_text()
    return re.sub(r'<script src="([\w.-]+\.js)"></script>', lambda m: f"<script>{body(m[1])}</script>", html)


def page(static: Path, fixture: dict) -> str:
    """`static/index.html` with its bundle inlined and `fixture` embedded ahead of it."""
    html = (static / "index.html").read_text()
    data = json.dumps(fixture).replace("</", "<\\/")

    def script(m: re.Match) -> str:
        js = (static / m[1]).read_text().replace("</script", "<\\/script")
        return f'<script>window.__FLOW_FIXTURE__ = {data}</script>\n  <script type="module">{js}</script>'

    def style(m: re.Match) -> str:
        return f"<style>{(static / m[1]).read_text()}</style>"

    html = re.sub(r'<script type="module" crossorigin src="/([^"]+)"></script>', script, html)
    return re.sub(r'<link rel="stylesheet" crossorigin href="/([^"]+)">', style, html)


def build(out: Path, server: str, design: Path | None = None) -> Path:
    """Write the demo page to `out`: from the design mockup in `design` when given, else from `server`'s snapshot."""
    out.write_text(mockup(design) if design else page(STATIC, scrub(capture(server))))
    return out


def main(argv: list[str] | None = None) -> None:  # pragma: no mutate block — CLI process boundary
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--server", default="http://127.0.0.1:8766")
    ap.add_argument("--mockup", type=Path, help="a design mockup directory to build instead of StarPulse")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    print(build(args.out, args.server, args.mockup))


if __name__ == "__main__":
    main()
