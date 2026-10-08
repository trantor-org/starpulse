// Design mockup layer (the Kanban, DAGs and start-question UI polish), never part of the page. The page above is the branch's real page over the PR demo's
// capture. This layer adds the review bar, the harnesses the start question offers (?harness=two|one|none; a demo page has none),
// a start that the session-start service accepts, a stack held open (?s=stack) or the start question asked (?s=start) on load,
// and the text size (?fs=100|125|150). It runs before the page's module.
(() => {
  const q = new URLSearchParams(location.search);
  if (!q.has("view")) { q.set("view", "kanban"); history.replaceState(null, "", `?${q}`); }
  try {
    const k = "fv.admin.prefs", p = JSON.parse(localStorage.getItem(k) || "{}");
    p.scale = Number(q.get("fs") || 100);
    localStorage.setItem(k, JSON.stringify(p));
  } catch { /* storage off: the page keeps 100% */ }

  // apply-on-merge's live step graph (17 steps, a ten-way fan into verify_applied) and its GitHub workflow, which the demo capture
  // lacks: mid-run (?apply=run), last run passed (done) or failed at one fan step (fail).
  const F = window.__FLOW_FIXTURE__;
  if (F) {
    const apply = q.get("apply") || "run", iso = (s) => new Date(s * 1000).toISOString().replace(/\.\d+Z$/, "Z");
    const fan = ["apply_unraid", "apply_rulesets", "apply_board", "apply_flow_view", "apply_machine_event_mapper", "apply_session_start", "apply_skills_claude", "apply_skills_codex", "apply_skills_unraid"];
    const graph = [["validate_event", []], ["classify", ["validate_event"]], ["apply_migrations", ["classify"]], ["apply_images", ["apply_migrations"]],
      ["apply_deploy", ["apply_images"]], ["apply_systemd", ["apply_deploy"]], ["push_dashboards", ["apply_systemd"]], ...fan.map((n) => [n, ["classify"]]),
      ["verify_applied", ["push_dashboards", ...fan]]];
    const run = { validate_event: "succeeded", classify: "succeeded", apply_migrations: "succeeded", apply_images: "running", apply_unraid: "succeeded",
      apply_rulesets: "succeeded", apply_board: "running", apply_flow_view: "running", apply_machine_event_mapper: "queued", apply_session_start: "queued" };
    const at = (n) => apply === "done" ? "succeeded" : apply === "fail" ? (n === "apply_board" ? "failed" : n === "verify_applied" ? "skipped" : "succeeded") : run[n] ?? "not_started";
    const steps = graph.map(([name, depends]) => ({ name, depends, status: at(name), kind: null }));
    const end = F.now - 1500, start = apply === "run" ? F.now - 95 : end - 212;
    F.dags.push({ name: "dagu/apply-on-merge", status: apply === "run" ? "running" : apply === "fail" ? "failed" : "succeeded", runId: "apply-demo-1",
      startedAt: iso(start), finishedAt: apply === "run" ? "" : iso(end), steps, pool: "default",
      active: apply === "run" ? [{ runId: "apply-demo-1", status: "running", startedAt: iso(start), step: "apply_images", stepStartedAt: iso(F.now - 40),
        steps: Object.fromEntries(steps.map((s) => [s.name, s.status])) }] : [] });
    const job = (j, ss) => ss.map((s, i) => [`${j} / ${s}`, [i ? `${j} / ${ss[i - 1]}` : j]]);
    const A = "Apply merged changes through Dagu", G = "Submit code graph refresh to Dagu";
    const wf = [[A, []], ...job(A, ["Set up job", "Set up runner", "Fast-forward the shared checkout", "Validate the push", "Submit the merge to Dagu", "Complete runner", "Complete job"]),
      ["Page on two consecutive failed applies", [A]], [G, [A]], ...job(G, ["Set up job", "Set up runner", "Submit", "Complete runner", "Complete job"])];
    F.dags.push({ name: "github/apply-on-merge.yml", status: "succeeded", runId: "gh-demo-1", startedAt: iso(end - 260), finishedAt: iso(end - 20), pool: "default", active: [],
      steps: wf.map(([name, depends]) => ({ name, depends, status: name.startsWith("Page on") ? "skipped" : "succeeded", kind: null })) });
    const dom = F.domains.find((d) => d.name === "Delivery & CI") || F.domains[0];
    dom.dags.push({ name: "dagu/apply-on-merge", runSafe: false }, { name: "github/apply-on-merge.yml", runSafe: false });
  }

  // The live server's /api/harnesses, and a second harness for the Harness picker; ?harness=none is a server that names none.
  const claude = { name: "claude", label: "Claude Code", sessions: true, reason: null,
    tiers: { fast: { model: "haiku", efforts: [] }, standard: { model: "sonnet", efforts: ["medium", "high"] }, deep: { model: "opus", efforts: ["medium", "high"] } } };
  const codex = { name: "codex", label: "Codex", sessions: true, reason: null,
    tiers: { standard: { model: "gpt-5", efforts: ["low", "medium", "high"] }, deep: { model: "gpt-5-pro", efforts: ["high"] } } };
  const set = { two: [claude, codex], one: [claude], none: [] }[q.get("harness") || "two"] || [claude, codex];
  window.__MOCK_API__ = {
    "/api/harnesses": () => (set.length ? [{ tiers: ["fast", "standard", "deep"], harnesses: set }, 200] : [{ error: "no harness configured" }, 503]),
    "/api/start": () => [{ url: "#session", at: Date.now() / 1000 }, 200],
  };

  // A starting state, once the board has drawn: a Waiting stack held open, or the start question on the first startable card.
  const s = q.get("s");
  if (s) {
    const until = (find, act, tries = 80) => {
      const el = find();
      if (el) act(el);
      else if (tries) setTimeout(() => until(find, act, tries - 1), 100);
    };
    if (s === "stack") until(() => document.querySelector(".stack .card"), (el) => el.focus());
    if (s === "start") until(() => document.querySelector(".card.startable button.play:not(:disabled)"), (el) => setTimeout(() => el.click(), 300));
  }

  // The review bar: every variant, each a link to its own address.
  const bar = document.createElement("div");
  bar.id = "mockbar";
  bar.innerHTML = `<style>
    #mockbar { position: fixed; z-index: 50; bottom: 12px; left: 50%; transform: translateX(-50%); display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; justify-content: center;
      max-width: calc(100vw - 540px); padding: 6px 10px; border-radius: 9px; border: 1px dashed rgba(251,191,36,.45); background: rgba(10,12,20,.9); font: 11px Inter, system-ui, sans-serif; color: #6b7a93; }
    #mockbar b { color: #fbbf24; font-weight: 500; letter-spacing: .2em; font-size: 9.5px; }
    #mockbar span { display: inline-flex; gap: 3px; align-items: center; }
    #mockbar a { padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(148,163,184,.18); color: #b6c0d3; text-decoration: none; }
    #mockbar a.on { border-color: #fbbf24; color: #fde68a; background: rgba(251,191,36,.10); }
  </style><b>MOCKUP</b>`;
  const cur = { view: q.get("view"), s: q.get("s") || "", harness: q.get("harness") || "two", apply: q.get("apply") || "run", fs: q.get("fs") || "100" };
  const groups = [
    ["View", "view", [["kanban", "Kanban"], ["dags", "DAGs"], ["constellation", "Star Map"]]],
    ["Open", "s", [["", "Nothing"], ["stack", "Stack"], ["start", "Start question"]]],
    ["apply-on-merge", "apply", [["run", "Running"], ["done", "Passed"], ["fail", "Failed"]]],
    ["Harnesses", "harness", [["two", "Two"], ["one", "One"], ["none", "None"]]],
    ["Text", "fs", [["100", "100%"], ["125", "125%"], ["150", "150%"]]],
  ];
  for (const [title, key, opts] of groups) {
    const g = document.createElement("span");
    g.append(title);
    for (const [v, l] of opts) {
      const a = document.createElement("a"), u = new URLSearchParams(location.search);
      if (v) u.set(key, v);
      else u.delete(key);
      // the stack and the start question are on the Kanban
      if (key === "s" && v) u.set("view", "kanban");
      if (key === "apply") u.set("view", "dags");
      a.href = `?${u}`;
      a.textContent = l;
      if (cur[key] === v) a.className = "on";
      g.append(a);
    }
    bar.append(g);
  }
  document.addEventListener("DOMContentLoaded", () => document.body.append(bar));
  if (document.body) document.body.append(bar);
})();
