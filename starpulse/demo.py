"""Build StarPulse as one self-contained HTML file that runs with no server.

    .venv/bin/python -m starpulse.demo --server http://127.0.0.1:8766 --out .tmp/flow-demo.html
    .venv/bin/python -m starpulse.demo --mockup <the design mockup directory> --out .tmp/mockup-demo.html
    .venv/bin/python -m starpulse.demo --elements design/elements --out .tmp/element-sheet.html

It reads a running starpulse.server's snapshot for its structure (the
machines, the DAGs and their steps) and replaces every task with a synthetic
one in the same state, so no task text, PR or address leaves. The
built page in `static/` is inlined around the result, which the page reads as
`window.__FLOW_FIXTURE__` and animates as `?demo` does. `--mockup` does the same
for a design mockup's saved `data.js`, keeping each session's link to its task. `--elements` inlines the element
sheet's stylesheet and script, so the palette page is one file too.
"""

import argparse
import collections
import itertools
import json
import re
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from starpulse.analytics import move_shares
from starpulse.board_feed import SUN_DAYS
from starpulse.upstream_backlog import board_machine

STATIC = Path(__file__).parent / "static"
#: Board labels that say what kind of work a task is and nothing about it.
LABELS = re.compile(r"^(kind-[a-z]+|size-\d+|agent-resolvable|needs-human|adr-needed|bug|feature)$")
#: The mockup data keys `scrub_mockup` knows how to clean; any other key is refused rather than passed through.
MOCKUP_KEYS = {"now", "dags", "writers", "launches", "cues", "domains", "descriptions", "flows"}
#: The saved Board keys `scrub_board` knows how to clean, refused the same way.
BOARD_KEYS = {"now", "names", "tasks"}
#: An agent profile assignee, the only kind a demo keeps.
PROFILE = re.compile(r"^@agent-[a-z-]+$")
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


def _demo_dag(index: int, dag: dict) -> dict:
    """`dag` under run ids that name no real run, its active runs numbered after it."""
    demo = {**dag, "runId": f"demo-{index}"}
    if "active" in dag:
        demo["active"] = [{**run, "runId": f"demo-{index}-{n}"} for n, run in enumerate(dag["active"])]
    return demo


#: The steps of the seeded `deliver` DAG, and the runs seeded in flight on it: the step each is in and the seconds since it entered it.
DELIVER_STEPS = ("refuse", "lint", "commit", "push", "open_pr", "wait_ci", "ready")
SEEDED_RUNS = (("wait_ci", 300), ("lint", 60), ("wait_ci", 450))
#: The seeded concurrency pools and their caps; `deliver` is the one the seeded runs hold.
SEEDED_POOLS = {"deliver": 32, "default": 2}


def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_fanout(domains: list[dict], dags: list[dict], now: float) -> tuple[list[dict], list[dict]]:
    """A `deliver` DAG with runs in flight and the pools it runs on, for a capture whose runs adapter reports none.

    CI's server has no runs adapter to read, so the page's Queues section and each DAG's fan-out would draw nothing.
    The DAG takes the instance prefix of the `deliver` workflow the domains declare; none declared, or one the capture
    already reads, nothing is seeded.
    """
    name = next((d["name"] for g in domains for d in g["dags"] if d["name"].rpartition("/")[2] == "deliver"), None)
    if name is None or any(d["name"] == name for d in dags):
        return [], []
    prefix = f"{name.rpartition('/')[0]}/" if "/" in name else ""

    def statuses(step: str) -> dict[str, str]:
        at = DELIVER_STEPS.index(step)
        return {
            s: "succeeded" if i < at else "running" if i == at else "not_started" for i, s in enumerate(DELIVER_STEPS)
        }

    runs = [
        {
            "runId": f"deliver-agent-demo-{n}",
            "status": "running",
            "startedAt": _iso(now - seconds - 150),
            "step": step,
            "stepStartedAt": _iso(now - seconds),
            "steps": statuses(step),
        }
        for n, (step, seconds) in enumerate(SEEDED_RUNS, 1)
    ]
    steps = [
        {"name": s, "depends": [DELIVER_STEPS[i - 1]] if i else [], "status": runs[0]["steps"][s], "kind": None}
        for i, s in enumerate(DELIVER_STEPS)
    ]
    dag = {
        "name": name,
        "status": "running",
        "runId": runs[0]["runId"],
        "startedAt": runs[0]["startedAt"],
        "finishedAt": "",
        "steps": steps,
        "active": runs,
        "pool": f"{prefix}deliver",
    }
    pools = [
        {"name": f"{prefix}{p}", "cap": cap, "running": len(runs) if p == "deliver" else 0, "queued": 0}
        for p, cap in SEEDED_POOLS.items()
    ]
    return [dag], pools


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
    # A Waiting chain under index 3, so the Kanban folds them into a stack: 14 waits on 3, 15 and 16 on 14.
    ("waiting", "m-2", ["size-3", "kind-feature"], 3, "@agent-standard-high", None),
    ("waiting", "m-2", ["size-2"], 14, "@agent-fast-low", None),
    ("waiting", "m-2", ["size-1", "kind-bug"], 14, "", None),
    # A Done chain on index 12, so the Kanban's Done column folds them into a stack: 17 depends on 12 and 18 on 17.
    ("done", "m-1", ["size-2"], 12, "@agent-standard-high", ("pass", True, 0)),
    ("done", "m-1", ["size-1", "kind-feature"], 17, "@agent-deep-high", ("pass", True, 0)),
]


#: The lanes `SEED` fills, as the Board machine a capture with no board of its own is drawn on: CI's native board has
#: three lanes, which the Kanban would draw as three columns and leave every other seeded card without one.
SEED_LANES = ("Ready", "Waiting", "In Progress", "Review", "Needs attention", "Done")

#: How long before the capture each seeded task created that day was created, by its index in `SEED`.
SEED_CREATED = {0: 900, 1: 2400}
#: The seeded tasks settled that day: where each settled, how long before the capture, and its assignee.
SEED_SETTLED = [
    ("completed", 1200, "@agent-standard-high"),
    ("completed", 3000, "@agent-deep-high"),
    ("completed", 5400, "@agent-fast-low"),
    ("archived", 4200, ""),
]
#: How far back a settled task is still the day's; a capture keeps no older one.
DAY_S = 86400


def _seed(now: float) -> tuple[list[dict], dict, dict]:
    """`SEED` as a live Board's tasks, the pull requests the server would have read for them, and the day's settled tasks."""
    ids = [f"seed-{i}" for i in range(len(SEED))]
    agents, pulls = [], {}
    for i, (state, milestone, labels, after, model, pull) in enumerate(SEED):
        agents.append(
            {"id": ids[i], "state": state, "model": model, "milestone": milestone, "labels": labels}
            | ({"dependencies": [ids[after]]} if after is not None else {})
            | ({"created": now - SEED_CREATED[i]} if i in SEED_CREATED else {})
        )
        if pull:
            checks, merged, threads = pull
            pulls[ids[i]] = [{"checks": checks, "merged": merged, "threads": threads}]
    settled = {
        f"seed-settled-{i}": {"state": state, "at": now - age, "created": None, "title": "", "model": model}
        for i, (state, age, model) in enumerate(SEED_SETTLED)
    }
    return agents, pulls, settled


def scrub(live: dict) -> dict:
    """`live` with its structure kept and every task, settled task, run id and address replaced.

    A task keeps one demo name wherever it is drawn, so a machine's task still sits on the Board. A Board task keeps
    its lane and when it entered it, its milestone (renamed `m-N`), its kind and size labels, the dependencies that
    are on the Board and a synthetic description; its pull requests keep their checks and threads but lose their
    number and address.
    """
    names: dict[str, str] = {}
    board = [a for f in live["flows"] if f["name"] == "board" for a in f["agents"]]
    pulls, settled = live.get("pulls", {}), live.get("settled", {})
    if not board:
        board, pulls, settled = _seed(live["now"])
        live = {
            **live,
            "flows": [
                {**f, "machine": board_machine(SEED_LANES)} if f["name"] == "board" else f for f in live["flows"]
            ],
        }
    for a in board:  # the Board's tasks are DEMO-1.. in Board order, whichever flow comes first
        names.setdefault(a["id"], f"DEMO-{len(names) + 1}")
    keys = sorted({a["milestone"] for a in board if a.get("milestone")}, key=lambda k: (len(k), k))
    milestones = {k: f"m-{i + 1}" for i, k in enumerate(keys)}

    def task(a: dict, *, is_board: bool) -> dict:
        name = names.setdefault(a["id"], f"DEMO-{len(names) + 1}")
        demo = _task(int(name.removeprefix("DEMO-")) - 1, a)
        if is_board:
            return (
                demo
                | {
                    "milestone": milestones.get(a.get("milestone"), ""),
                    "labels": [x for x in a.get("labels", []) if LABELS.match(x)],
                    "dependencies": [names[d] for d in a.get("dependencies", []) if d in names],
                    "description": f"Synthetic demo task: {demo['title'].lower()}.",
                    **({"entered": a["entered"]} if "entered" in a else {}),
                }
                | ({"created": a["created"]} if a.get("created") is not None else {})
            )
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

    def settled_task(id_: str, entry: dict) -> tuple[str, dict]:
        name = names.setdefault(id_, f"DEMO-{len(names) + 1}")
        demo = _task(int(name.removeprefix("DEMO-")) - 1, entry)
        return name, {k: entry.get(k) for k in ("state", "at", "created")} | {
            "title": demo["title"],
            "model": demo["model"],
        }

    day = dict(
        settled_task(id_, e) for id_, e in settled.items() if e.get("at") is not None and e["at"] > live["now"] - DAY_S
    )
    seeded_dags, seeded_pools = (
        ([], []) if live.get("pools") else _seed_fanout(live["domains"], live["dags"], live["now"])
    )
    history, captured = _history(flows, live["now"]), live.get("suns", {})  # a fresh server's shares are all zero
    return {
        **live,
        "boardUrl": None,
        "hint": None,
        "domains": [{**d, "dags": [{"name": x["name"], "runSafe": False} for x in d["dags"]]} for d in live["domains"]],
        "dags": [_demo_dag(i, d) for i, d in enumerate(live["dags"])] + seeded_dags,
        **({"pools": seeded_pools} if seeded_pools else {}),
        "flows": flows,
        "pulls": {
            names[t]: [
                p | {"number": 100 + int(names[t].removeprefix("DEMO-")) - 1, "url": "#", "stale": False} for p in ps
            ]
            for t, ps in pulls.items()
            if t in names and ps
        },
        "settled": day,
        "error": None,
        "history": history,
        "suns": captured if any(captured.values()) else _suns(flows, history, live["now"]),
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


def _suns(flows: list[dict], history: dict[str, list[dict]], now: float) -> dict[str, float]:
    """The Board states' sun shares from the demo's synthetic lane changes, as the server sizes them from the store."""
    board = next(f for f in flows if f["name"] == "board")
    rows = [(t, c["at"], c["from"], c["to"]) for t, changes in history.items() for c in changes]
    return move_shares(board["machine"], rows, start=now - SUN_DAYS * DAY_S, end=now)


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


def scrub_board(board: dict, renames: dict[str, str]) -> dict:
    """A design mockup's saved Board (`window.BOARD`) with each task renamed as `renames` names it, the rest numbered on
    after them, and only its lane, milestone, kind labels, profile, pull request states and move verdicts kept."""
    if unknown := set(board) - BOARD_KEYS:
        raise ValueError(f"mockup board has keys the scrub does not know: {sorted(unknown)}")
    names, more = dict(renames), itertools.count(len(renames) + 1)
    for t in board["tasks"]:
        if t["id"] not in names:
            names[t["id"]] = f"DEMO-{next(more)}"
    prs = itertools.count(1)

    def task(i: int, t: dict) -> dict:
        return {
            "id": names[t["id"]],
            "title": TITLES[i % len(TITLES)],
            "lane": t["lane"],
            "milestone": t.get("milestone"),
            "labels": [x for x in t.get("labels", []) if LABELS.match(x)],
            "assignee": t["assignee"] if PROFILE.match(t.get("assignee") or "") else "",
            "dependencies": [names[d] for d in t.get("dependencies", []) if d in names],
            "prs": [
                {"number": next(prs), **{k: p[k] for k in ("checks", "merged", "threads") if k in p}}
                for p in t.get("prs", [])
            ],
            "live": t.get("live"),
            "moves": t.get("moves", {}),
            "entered": t.get("entered"),
        }

    return {**board, "tasks": [task(i, t) for i, t in enumerate(board["tasks"])]}


def mockup(design: Path) -> str:
    """`design/index.html` with every local script inlined: `data.js` scrubbed, `history.js` (lane changes keyed by
    task id) renamed like the Board with tasks off it dropped, `board.js` (a saved Board) renamed like it too, and any
    other script as it is."""
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
        if name == "board.js":
            board = json.loads(src[src.index("{") : src.rindex("}") + 1])
            return "window.BOARD = " + json.dumps(scrub_board(board, renames)).replace("</", "<\\/") + ";"
        return src.replace("</script", "<\\/script")

    html = (design / "index.html").read_text()
    return re.sub(r'<script src="([\w.-]+\.js)"></script>', lambda m: f"<script>{body(m[1])}</script>", html)


def elements(sheet: Path) -> str:
    """`sheet/index.html` as one file: each local stylesheet link inlined as a `<style>` without its comments, each local
    script as a `<script>`."""

    def style(m: re.Match) -> str:
        css = (sheet / m[1]).resolve().read_text()
        return f"<style>{re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)}</style>"  # its comments name tasks

    def script(m: re.Match) -> str:
        return f"<script>{(sheet / m[1]).read_text().replace('</script', '<\\/script')}</script>"

    html = (sheet / "index.html").read_text()
    html = re.sub(r'<link rel="stylesheet" href="((?![a-z]+:)[^"]+)">', style, html)
    return re.sub(r'<script src="([\w.-]+\.js)"></script>', script, html)


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


def build(out: Path, server: str, design: Path | None = None, sheet: Path | None = None) -> Path:
    """Write the demo page to `out`: the element sheet in `sheet` or the design mockup in `design` when given, else
    `server`'s snapshot."""
    out.write_text(elements(sheet) if sheet else mockup(design) if design else page(STATIC, scrub(capture(server))))
    return out


def main(argv: list[str] | None = None) -> None:  # pragma: no mutate block — CLI process boundary
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--server", default="http://127.0.0.1:8766")
    ap.add_argument("--mockup", type=Path, help="a design mockup directory to build instead of StarPulse")
    ap.add_argument("--elements", type=Path, help="the element sheet directory to build instead of StarPulse")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    print(build(args.out, args.server, args.mockup, args.elements))


if __name__ == "__main__":
    main()
