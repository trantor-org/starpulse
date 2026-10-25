// Preview only: the mock states the Star Map's phase branches were approved against (Round 22), reached with `?mock=1` and `&sim=1|2|3`.
import type { Snapshot } from "../api";

/** Seconds between the simulated tasks' steps under `&sim=N`. */
export const SIM_PERIOD = 4;
/** Preview only (Round 22's mock states): `?mock=1` puts the first two In Progress tasks in their phases, `&extra=N` adds N simulated tasks, and a banner says so. */
export function mocked(snap: Snapshot): Snapshot {
  const q = typeof location === "undefined" ? null : new URLSearchParams(location.search);
  if (q?.get("mock") !== "1") return snap;
  const now = snap.now ?? Date.now() / 1000, models = ["@agent-deep-high", "@agent-standard-high", "@agent-standard-medium"];
  const spots: [string, string][] = [["build", "worktree_ready"], ["build", "red_proven"], ["deliver", "lint_green"], ["deliver", "ci_green"], ["review_fix", "start"], ["build", "green"], ["deliver", "pushed"], ["build", "criteria_checked"]];
  const extra = Array.from({ length: Number(q.get("extra") ?? 0) }, (_, i) => ({ id: `SIM-${i + 1}`, spot: spots[i % spots.length], model: models[i % models.length] }));
  // the two tasks the mock walks: the Board's first two In Progress tasks
  const pair = (snap.flows.find((f) => f.name === "board")?.agents ?? []).filter((a) => a.state === "in_progress").slice(0, 2).map((a) => a.id);
  const at: Record<string, [string, string]> = { ...(pair[0] && { [pair[0]]: ["build", "green"] as [string, string] }), ...(pair[1] && { [pair[1]]: ["deliver", "pr_opened"] as [string, string] }), ...Object.fromEntries(extra.map((e) => [e.id, e.spot])) };
  // `&sim=1`: each task takes the next step of one walk every SIM_PERIOD seconds, through Build, Deliver and Review Fix and out to a moon and
  // back, each task a few steps behind the one before
  // `&sim=2`: the two tasks alone walk one task's whole life, through six machines: Build, a skill it runs mid-build, Deliver, CI going red
  // then green, the review triage Deliver opens, and Review Fix, half a walk apart
  // `&sim=3`: both tasks open a PR in Deliver, then sit on the same step of the CI it opens, failing, so their dots stack on one station
  const sim = ["1", "2", "3"].includes(q.get("sim") ?? ""), walked: Record<string, number> = {};
  if (q.get("sim") === "3") {
    for (const id of pair) at[id] = performance.now() < SIM_PERIOD * 1000 ? ["deliver", "pr_opened"] : ["ci", "failing"];
    Object.assign(walked, { ci: now, deliver: now - SIM_PERIOD, build: now - 2 * SIM_PERIOD });
  } else if (q.get("sim") === "2") {
    const walk = [["board", "ready"], ["build", "start"], ["build", "worktree_ready"], ["build", "red_proven"], ["graph-traversal", "oriented"], ["graph-traversal", "anchored"], ["graph-traversal", "expanded"], ["build", "green"], ["build", "criteria_checked"], ["deliver", "lint_green"], ["deliver", "committed"], ["deliver", "pushed"], ["deliver", "pr_opened"], ["ci", "running"], ["ci", "failing"], ["ci", "running"], ["ci", "passing"], ["triaging-cr-reviews", "audit_active"], ["triaging-cr-reviews", "fix_verified"], ["triaging-cr-reviews", "fix_replied"], ["deliver", "ci_green"], ["review_fix", "start"], ["board", "review"]] as [string, string][];
    const n = Math.floor(Date.now() / 1000 / SIM_PERIOD);
    pair.forEach((id, i) => {
      const k = (n + i * Math.floor(walk.length / 2)) % walk.length;
      at[id] = walk[k];
      // a machine's last activity is the newest step either task took in it, so the drill-down ranks the machines in use first
      for (let j = walk.length - 1; j >= 0; j--) {
        const [flow] = walk[(k - j + walk.length) % walk.length];
        if (flow !== "board") walked[flow] = Math.max(walked[flow] ?? 0, (n - j) * SIM_PERIOD);
      }
    });
  } else if (sim) {
    const steps = (name: string) => (snap.flows.find((f) => f.name === name)?.machine.states ?? []).filter((s) => !s.final).map((s): [string, string] => [name, s.id]);
    // the walk starts at Ready and ends at Review on the Board, so a task is seen entering the phases and leaving them
    const route = [["board", "ready"] as [string, string], ...steps("build"), ...steps("deliver"), ["ci", "running"] as [string, string], ["ci", "passing"] as [string, string], ...steps("review_fix"), ["board", "review"] as [string, string]], n = Math.floor(Date.now() / 1000 / SIM_PERIOD);
    Object.keys(at).forEach((id, i) => (at[id] = route[(n + i * 3) % route.length]));
  }
  // the live snapshot names DAGs `pushed/<name>` and `pushed/dagu/<name>`; the map ties `dagu/<name>`, so fold both onto that, a running or failed run first
  const rank = (st: string) => (st === "running" ? 0 : st === "failed" ? 1 : 2);
  // a preview's Dagu adapter has no credentials and lists no DAG: every declared DAG stands in as idle
  const iso = new Date(now * 1000).toISOString(), declared = [...new Set((snap.domains ?? []).flatMap((d) => d.dags.map((x) => x.name)))];
  const listed = snap.dags.length ? snap.dags : declared.map((name) => ({ name, runId: "mock", status: name === "dagu/dependency-update-investigation" ? "running" : "succeeded", startedAt: iso, finishedAt: iso, steps: [] }) as unknown as Snapshot["dags"][number]);
  const simBoard: Record<string, string[]> = { PR_OPENED: ["dagu/deliver"], SEND_BACK: ["dagu/auto-rebase"], RESUME: ["dagu/ci-validate-redispatch"] };
  // under a sim, the DAG that drives a machine runs while a walking task is in it, so its hangar and orbiter show
  const drives: Record<string, string> = { deliver: "dagu/deliver", ci: "dagu/ci-validate-redispatch", "graph-traversal": "dagu/graph-refresh", "triaging-cr-reviews": "dagu/auto-rebase", review_fix: "dagu/auto-rebase" };
  // the Board's own DAGs take turns too, half of them running at a time for three steps each, so hangars draw on and tear down through a walk
  const turn = Math.floor(Date.now() / 1000 / SIM_PERIOD / 3), board = Object.values(simBoard).flat().filter((_, i) => (turn + i) % 2 === 0);
  const driving = new Set(sim ? [...Object.values(at).map(([flow]) => drives[flow]), ...board] : []);
  const dags = [...listed].map((d) => ({ ...d, name: `dagu/${d.name.replace(/^pushed\//, "").replace(/^dagu\//, "")}` })).map((d) => (driving.has(d.name) ? { ...d, status: "running" as const } : d)).sort((a, b) => rank(a.status) - rank(b.status)).filter((d, i, all) => all.findIndex((x) => x.name === d.name) === i);
  // simulated DAG writers: no live Board or phase event has a DAG writer yet, so these show how one would tie in
  const W = (dag: string) => ({ actor: dag, trigger: "dagu (simulated)" });
  const simFlow: Record<string, Record<string, string[]>> = {
    deliver: { COMMITTED: ["dagu/deliver"], PUSHED: ["dagu/deliver"], PR_OPENED: ["dagu/deliver"], CI_RED: ["dagu/ci-sp-retry"], CI_GREEN: ["dagu/ci-sp-retry"] },
    review_fix: { REVIEW_RECORDED: ["dagu/cr-sweep"] },
    "auditing-infrastructure": { SCOPE_DELTA_SELECTED: ["dagu/nightly-audit"], REPORT_WRITTEN: ["dagu/nightly-audit"] },
    "running-skill-evals": { REQUESTED: ["dagu/skill-eval"], OUTCOME_PASSED: ["dagu/skill-eval"], OUTCOME_FAILED: ["dagu/skill-eval"] },
  };
  const simTies: Record<string, { kind: "observed"; machine: string; state: string; count: number }> = {
    "graph-traversal": { kind: "observed", machine: "build", state: "red_proven", count: 2 },
    ci: { kind: "observed", machine: "deliver", state: "pr_opened", count: 2 },
  };
  const withSim = (ws: Record<string, { actor: string; trigger: string }[]> | null | undefined, sim: Record<string, string[]> = {}) => {
    const out = { ...(ws ?? {}) };
    for (const [ev, ds] of Object.entries(sim)) out[ev] = [...(out[ev] ?? []), ...ds.map(W)];
    return out;
  };
  const flows = snap.flows.map((f) => {
    if (f.name === "board") {
      const m = f.machine as typeof f.machine & { dagActors?: string[]; launches?: Record<string, { skill: string; machine: string | null }> };
      const machine = { ...m, writers: withSim(m.writers, simBoard), dagActors: [...(m.dagActors ?? []), ...Object.values(simBoard).flat()], launches: { ...(m.launches ?? {}), "dagu/deliver": { skill: "deliver", machine: "deliver" }, "dagu/ci-sp-retry": { skill: "deliver", machine: "deliver" }, "dagu/cr-sweep": { skill: "triaging-cr-reviews", machine: "review_fix" } } };
      // under `&sim=1` a walking task is on the Board's Ready or Review while the walk has it there, and In Progress while it is in a phase
      const board = (id: string, st: string) => (!sim || !at[id] ? st : at[id][0] === "board" ? at[id][1] : "in_progress");
      const agents = [...f.agents, ...extra.map((e) => ({ id: e.id, title: `Simulated task ${e.id}`, state: "in_progress", model: e.model, entered: now - 3600, created: now - 7200 }))];
      return { ...f, machine, agents: agents.map((a) => ({ ...a, state: board(a.id, a.state) })) } as typeof f;
    }
    if (simFlow[f.name]) f = { ...f, machine: { ...f.machine, writers: withSim(f.machine.writers, simFlow[f.name]) } } as typeof f;
    // the skills a phase runs mid-way are tied by observation in a live board; the preview's history is empty, so the walk's own ties stand in
    if (walked[f.name] !== undefined) f = { ...f, last: walked[f.name], ...(simTies[f.name] && !f.ties?.length && { ties: [simTies[f.name]] }) } as typeof f;
    const mine = Object.entries(at).filter(([, [flow]]) => flow === f.name);
    if (!mine.length) return f;
    const model = (id: string) => snap.flows.find((b) => b.name === "board")?.agents.find((a) => a.id === id)?.model ?? extra.find((e) => e.id === id)?.model ?? models[0];
    return { ...f, agents: [...f.agents, ...mine.map(([id, [, state]]) => ({ id, title: id, state, model: model(id), task: id, active: now }))] } as typeof f;
  });
  if (typeof document !== "undefined" && !document.getElementById("mock-banner")) {
    const b = document.createElement("div");
    b.id = "mock-banner";
    b.textContent = "Simulated phases" + (extra.length ? ` · +${extra.length} tasks` : "") + (sim ? ` · ${q.get("sim") === "3" ? "2 tasks on one CI step" : `${q.get("sim") === "2" ? "2 tasks through 6 machines, " : ""}a step every ${SIM_PERIOD} s`}` : "");
    b.title = `${pair.join(" and ")} walk the phases; DAG writers deliver, ci-sp-retry, cr-sweep, auto-rebase, ci-validate-redispatch, nightly-audit, skill-eval`;
    b.style.cssText = "position:fixed;right:262px;top:10px;z-index:99;padding:2px 8px;border-radius:6px;font:12px Inter,system-ui,sans-serif;color:#fbbf24;background:rgba(6,10,20,0.85);border:1px solid rgba(251,191,36,0.4);pointer-events:none";
    document.body.appendChild(b);
  }
  return { ...snap, flows, dags };
}
