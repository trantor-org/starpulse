"""Build the DAGs-processes mockup: the DAGs catalog with each domain fold packaged into process subfolds (doc-230, Approach A).

usage: python design/dags-processes/build.py [--fixture PATH] [--server URL] [--modules starpulse/web/node_modules]

A self-contained page, not a patched build: `page.html` draws the catalog in the real `#dg` markup under the real stylesheet,
which this inlines (comments dropped, as the element sheet's build does) into `index.html`. `data.js` holds the DAGs as the
live snapshot carries them (names, steps, statuses, run times, pools, run-safe flags) re-bucketed into doc-230's process
taxonomy. `--fixture` reuses a saved capture, else the server's first `/api/events` snapshot is read and saved there.
"""

import argparse
import base64
import json
import re
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
STYLE = HERE.parents[1] / "starpulse" / "web" / "src" / "style.css"

#: doc-230's initial dagu taxonomy, in page order; host timers and github stay flat.
TAXONOMY: dict[str, dict[str, list[str]] | str] = {
    "Delivery & CI": {
        "Merge apply": ["apply-on-merge", "host-apply-merged", "setup-vm-apply", "gitlink-bump-gap"],
        "CI gates": [
            "ci-sp-contract",
            "ci-sp-python",
            "ci-sp-retry",
            "ci-sp-static",
            "ci-sp-web",
            "ci-validate",
            "whole-repo-gate",
        ],
        "PR hygiene": ["cr-sweep", "deliver", "dependabot-alert-gap", "coderabbit-usage-metrics"],
        "Metrics & drift": [
            "github-actions-queue-metrics",
            "github-budget-sample",
            "github-rulesets-drift",
            "mutation-metrics",
            "mutation-sweep",
        ],
    },
    "Board": {
        "Reconcile": [
            "board-dependency-reconciliation",
            "board-reconcile-merged",
            "main-follow",
            "main-follow-reconcile",
        ],
        "Hygiene": [
            "backlog-sweep",
            "board-lint",
            "phantom-deletes-to-task",
            "drift-to-task",
            "post-merge-check-sweep",
            "worktree-reap",
        ],
    },
    "Agent jobs & evals": {
        "Investigations": ["alert-fix-recheck", "alert-investigation", "dependency-update-investigation"],
        "Evals & skills": [
            "skill-conformance",
            "skill-eval",
            "skill-eval-nightly",
            "skill-optimize",
            "operator-prompt-corpus",
        ],
        "Sinks & transcripts": [
            "session-transcript-stats",
            "starpulse-analytics-sink",
            "starpulse-board-sink",
            "starpulse-cursor-transcripts",
            "claude-bg-daemon-events",
        ],
        "Train & audit": [
            "correction-clusters",
            "enrichment-classifier-retrain",
            "task-duplicate-retrain",
            "task-replay",
            "trace-cluster-report",
            "nightly-audit",
            "weekly-code-audit",
            "renovate-ci-fix",
        ],
    },
    "Retrieval & tags": {
        "Index & RAG": [
            "graph-refresh",
            "memory-reindex",
            "rag-metrics",
            "rag-audit-nominations",
            "rag-injection-uptake",
        ],
        "Tags": ["semantic-tag-merges", "tag-analytics", "tag-optimizer", "tag-performers", "tag-signals"],
    },
    "Host ops & backups": {
        "Health & sweep": [
            "healthcheck",
            "grafana-rule-health",
            "leftover-reaper",
            "cleanup-workspace",
            "testcontainers-sweep",
            "superseded-images-sweep",
        ],
        "Backups & load": [
            "postgres-backup",
            "postgres-restore-verify",
            "grafana-db-snapshot",
            "starpulse-db-snapshot",
            "starpulse-load",
            "docs-autocommit",
        ],
    },
    "Host timers": "timers/",
    "github": "github/",
}


def capture(server: str) -> dict:
    """The DAG half of the server's first snapshot: what the catalog draws, nothing of the board."""
    with urllib.request.urlopen(f"{server}/api/events", timeout=20) as r:
        for raw in r:
            if raw.startswith(b"data:"):
                s = json.loads(raw[5:])
                break
    keep = ("name", "status", "startedAt", "finishedAt", "pool")
    dags = [
        {
            **{k: d.get(k) for k in keep},
            "active": [],
            "steps": [
                {
                    "name": x["name"],
                    "kind": x.get("kind") or "",
                    "status": x.get("status", ""),
                    "depends": x.get("depends", []),
                }
                for x in d["steps"]
            ],
        }
        for d in s["dags"]
        if not d["name"].startswith("pushed/")
    ]
    safe = [x["name"] for g in s["domains"] for x in g["dags"] if x.get("runSafe")]
    return {"now": s["now"], "dags": dags, "pools": s["pools"], "runSafe": safe}


def domains(snap: dict) -> list[dict]:
    """The snapshot's domains as doc-230 shapes them: `processes` per nested domain, flat `dags` their concatenation."""
    names, safe = {d["name"] for d in snap["dags"]}, set(snap["runSafe"])
    out = []
    for dom, spec in TAXONOMY.items():
        if isinstance(spec, str):
            members = sorted(n for n in names if n.startswith(spec))
            out.append({"name": dom, "dags": [{"name": n, "runSafe": n in safe} for n in members], "processes": []})
            continue
        procs = [
            {
                "name": p,
                "dags": [{"name": f"dagu/{w}", "runSafe": f"dagu/{w}" in safe} for w in ws if f"dagu/{w}" in names],
            }
            for p, ws in spec.items()
        ]
        out.append({"name": dom, "dags": [x for p in procs for x in p["dags"]], "processes": procs})
    return out


ap = argparse.ArgumentParser()
ap.add_argument("--fixture", type=Path)
ap.add_argument("--server", default="http://127.0.0.1:8766")
ap.add_argument(
    "--modules",
    type=Path,
    default=STYLE.parents[1] / "node_modules",
    help="the web package's node_modules, whose fonts are inlined",
)
a = ap.parse_args()
if a.fixture and a.fixture.exists():
    snap = json.loads(a.fixture.read_text())
else:
    snap = capture(a.server)
    if a.fixture:
        a.fixture.write_text(json.dumps(snap))
fixture = {"now": snap["now"], "dags": snap["dags"], "pools": snap["pools"], "domains": domains(snap)}
(HERE / "data.js").write_text("window.__DAGS_FIXTURE__ = " + json.dumps(fixture, separators=(",", ":")) + ";\n")
css = re.sub(r"/\*.*?\*/", "", STYLE.read_text(), flags=re.DOTALL)  # its comments name tasks


def font(m: re.Match) -> str:
    f = a.modules / m[1]
    return f'url("data:font/woff2;base64,{base64.b64encode(f.read_bytes()).decode()}")' if f.is_file() else m[0]


css = re.sub(r'url\("(@fontsource/[^"]+\.woff2)"\)', font, css)
html = (
    (HERE / "page.html")
    .read_text()
    .replace('<link rel="stylesheet" href="../../starpulse/web/src/style.css">', f"<style>{css}</style>", 1)
)
(HERE / "index.html").write_text(html)
print(HERE / "index.html")
