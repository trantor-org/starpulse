// Mockup layer: CI history in StarPulse, injected over a capture of the live page. The history is synthetic; the server
// that would record it does not exist yet.
// The operator's model (2026-10-07): CI is a lifecycle machine with a fixed model, mapped by config onto the Board states
// that need it (here In Progress and Review), and drawn like any other sub-machine. Nothing in the page is CI-specific:
//   glance  - the ci machine is a moon on each mapped state; a task whose latest event is a CI one orbits it
//   hover   - on the ci machine a task's tooltip and back trace are its CI trail: pushes, results, re-runs, conflicts
//   click   - a task's panel names its CI state and lists the trail
// The fixed model: Opened -> Running on a push; Running -> Passing or Failing when the checks end; Failing -> Running on a
// push or a re-run; Passing -> Running on a push; Passing or Failing -> Conflicting when main moves under the PR;
// Conflicting -> Running on the rebase; Passing -> Merged; Merged -> Opened when the task opens its next PR, as one agent
// per task runs through its PRs in order.
// Definitions (operator interview): a run is one push (head commit) of a PR; re-runs (GitHub attempt > 1) and rebases
// (a push that rewrote the branch) are counted apart; conflicts are each time the PR turned CONFLICTING against main.
// The Kanban card already names a task's latest machine and state, so it gets no CI treatment of its own; the task modal
// is left alone until its two-column rework lands.
(() => {
  const STATES = {
    map: {},
    "in-progress": { walk: ["In Progress"] },
    review: { walk: ["Review"] },
    ci: { walk: ["In Progress", "ci"] },
    hover: { walk: ["In Progress", "ci"], hover: "fail" },
    panel: { walk: ["In Progress", "ci"], click: "fail" },
    "review-ci": { walk: ["Review", "ci"] },
    kanban: { view: "kanban" },
  };
  // the Board states whose config maps the ci machine onto them
  const MAPPED = [["in_progress", "a PR is open"], ["review", "a PR is open"]];
  const qs = new URLSearchParams(location.search);
  const preset = STATES[qs.get("s")] || null;
  const H = 3600;

  // ---- the fixed CI machine ----
  const S = (id, name, initial = false, final = false) => ({ id, name, initial, final });
  const MACHINE = {
    states: [S("opened", "Opened", true), S("running", "Running"), S("passing", "Passing"), S("failing", "Failing"), S("conflicting", "Conflicting"), S("merged", "Merged")],
    transitions: [
      ["opened", "running", "PUSHED"], ["running", "passing", "CHECKS_PASSED"], ["running", "failing", "CHECKS_FAILED"],
      ["failing", "running", "PUSHED"], ["failing", "running", "RERUN"], ["passing", "running", "PUSHED"],
      ["passing", "conflicting", "CONFLICTED"], ["failing", "conflicting", "CONFLICTED"], ["conflicting", "running", "REBASED"],
      ["passing", "merged", "MERGED"], ["merged", "opened", "PR_OPENED"],
    ].map(([source, target, event]) => ({ source, target, event })),
  };

  // ---- synthetic history, seeded per task so a reload draws the same sky ----
  const seed = (s) => { let h = 2166136261; for (const c of s) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return () => ((h = Math.imul(h ^ (h >>> 15), 2246822507) ^ Math.imul(h ^ (h >>> 13), 3266489909)) >>> 0) / 4294967296; };
  // one PR's pushes as the trail its CI machine would record
  function trail(id, pr, k, now, force) {
    const rnd = seed(`${id}#${k}`), roll = rnd();
    const n = force?.pushes ?? (roll < 0.66 ? 1 : roll < 0.86 ? 2 : roll < 0.95 ? 3 : 4);
    const end = force?.end ?? (pr.merged ? now - (6 + rnd() * 70) * H : now - (0.4 + rnd()) * H), span = (2 + rnd() * 20) * H;
    const t = [], ev = (at, state, event) => t.push({ state, event, at });
    ev(end - span - 0.2 * H, "opened", "PR_OPENED");
    for (let i = 0; i < n; i++) {
      const at = end - span + (span * (i + rnd() * 0.4)) / n, last = i === n - 1, took = (4 + rnd() * 4) * 60;
      const conflict = force?.conflictAt === i || (!force && i > 0 && rnd() < 0.15);
      if (conflict) ev(at - (0.3 + rnd()) * H, "conflicting", "CONFLICTED");
      ev(at, "running", conflict ? "REBASED" : "PUSHED");
      const outcome = last ? (pr.merged || pr.checks === "pass" ? "pass" : pr.checks === "failing" ? "fail" : pr.checks === "pending" ? "pending" : "pass") : rnd() < 0.62 ? "fail" : "pass";
      if (outcome === "pending") continue;
      if (force?.rerunAt === i || (!force && outcome === "pass" && rnd() < 0.08)) {
        ev(at + took, "failing", "CHECKS_FAILED");
        ev(at + took + 0.25 * H, "running", "RERUN");
        ev(at + took * 2 + 0.25 * H, "passing", "CHECKS_PASSED");
      } else ev(at + took, outcome === "pass" ? "passing" : "failing", outcome === "pass" ? "CHECKS_PASSED" : "CHECKS_FAILED");
    }
    if (pr.merged) ev(end + 0.5 * H, "merged", "MERGED");
    if (force?.conflictNow) ev(now - 0.2 * H, "conflicting", "CONFLICTED");
    return t;
  }

  const PICK = {};
  let FX;
  Object.defineProperty(window, "__FLOW_FIXTURE__", {
    configurable: true,
    get: () => FX,
    set(fx) {
      FX = fx;
      const flows = fx.flows || [], boardFlow = flows.find((f) => f.name === "board"), board = boardFlow?.agents || [];
      const pulls = (fx.pulls = fx.pulls || {}), now = fx.now || Date.now() / 1000;
      // a task whose in-progress session moved within the half hour stays on that machine; a CI pick is one that has not
      const session = new Map((flows.find((f) => f.name === "in-progress")?.agents || []).map((a) => [a.task, a.active || 0]));
      const quiet = (a) => (session.get(a.id) ?? 0) < now - 0.5 * H;
      const taken = new Set();
      const free = (state, test = () => true) => board.find((a) => a.state === state && !pulls[a.id] && !taken.has(a.id) && test(a));
      const force = {};
      // In Progress: two failing (one with a long story), one running, one green; Review: the PRs it holds, one gone conflicting
      const want = [["fail", "failing", { pushes: 4, rerunAt: 1, conflictAt: 2, end: now - 0.15 * H }], ["fail2", "failing", { pushes: 2, end: now - 0.3 * H }],
        ["pending", "pending", { pushes: 2, end: now - 0.1 * H }], ["green", "pass", { pushes: 3, end: now - 0.25 * H }]];
      for (const [key, checks, f] of want) {
        const a = free("in_progress", quiet) || free("in_progress");
        if (!a) continue;
        pulls[a.id] = [{ number: 0, url: "#", checks, merged: false, threads: 0, stale: false }];
        PICK[key] = a.id; force[a.id] = f; taken.add(a.id);
      }
      // the live board may hold little in Review; move In Progress tasks along so the mockup shows that state's machine
      for (let k = board.filter((a) => a.state === "review").length; k < 3; k++) { const a = free("in_progress"); if (a) { a.state = "review"; taken.add(a.id); } }
      const openPr = (a) => pulls[a.id]?.some((p) => !p.merged);
      for (const a of board.filter((x) => x.state === "review" && !openPr(x)))
        (pulls[a.id] = pulls[a.id] || []).push({ number: 0, url: "#", checks: "pass", merged: false, threads: 0, stale: false });
      const rev = board.find((a) => a.state === "review");
      if (rev) { PICK.conflict = rev.id; force[rev.id] = { pushes: 3, conflictNow: true }; }
      // the scrubbed capture repeats a task's PR number and drops each task's PR links; number every PR once and link it back
      let n = 100;
      for (const a of board) for (const p of pulls[a.id] || []) { p.number = n++; p.url = `#pull/${p.number}`; }
      // the ci machine's agents: one per task in a mapped state with a PR, running through its PRs in order
      const mapped = new Set(MAPPED.map(([s]) => s)), agents = [];
      for (const a of board) {
        const ps = pulls[a.id];
        if (!mapped.has(a.state) || !ps?.length) continue;
        a.prs = ps.map((p) => p.url);
        const t = ps.flatMap((p, k) => trail(a.id, p, k, now, k === ps.length - 1 ? force[a.id] : null)).sort((x, y) => x.at - y.at);
        const last = t[t.length - 1];
        agents.push({ state: last.state, model: "github", steps: t.length, trail: t, active: last.at, id: a.id, title: a.title, task: a.id });
      }
      flows.push({ name: "ci", machine: MACHINE, agents });
      fx.graphs = [...(fx.graphs || []).filter((g) => g !== "ci"), "ci"];
      boardFlow.machine.subflows = [...(boardFlow.machine.subflows || []), ...MAPPED.map(([state, when]) => ({ state, flow: "ci", exits: {}, parent: "board", when }))];
      window.__CI = { PICK, agents };
    },
  });

  // ---- the mockup bar: a state picker, for viewers that cannot edit the address (an embedded copy) ----
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  function control() {
    if (document.getElementById("cimock")) return;
    const bar = document.createElement("div"), s = qs.get("s") || "";
    bar.id = "cimock";
    bar.innerHTML = `<span>mockup</span><select aria-label="Mockup state"><option value="">state…</option>${Object.keys(STATES).map((k) => `<option value="${k}"${k === s ? " selected" : ""}>${esc(k)}</option>`).join("")}</select>`;
    const st = bar.querySelector("select");
    st.addEventListener("change", () => { location.search = st.value ? `?s=${st.value}` : ""; });
    document.body.appendChild(bar);
  }
  const css = `#cimock{position:fixed;left:50%;bottom:10px;transform:translateX(-50%);z-index:60;display:flex;gap:8px;align-items:center;
    padding:5px 10px;border:1px solid rgba(148,163,184,.3);border-radius:8px;background:rgba(6,10,20,.85);color:#94a3b8;font:12px system-ui,sans-serif}
    #cimock select{background:#0b1220;color:#dbe4f3;border:1px solid rgba(148,163,184,.35);border-radius:5px;font:inherit;padding:2px 4px}`;

  // ---- presets: reach a state the way a user does, by pointing at the bodies the page draws ----
  const probe = () => window.flowProbe?.();
  const target = (name) => probe()?.targets?.find((t) => t.name === name);
  // a level is opened from its row in the navigator's Layers, which a user can click at any text size; on the canvas a
  // small Board draws task dots over a state's body. The ci row shows under whichever mapped state is open.
  const row = (name) => [...document.querySelectorAll("#nav button.node")].find((b) => b.textContent.replace(/[▸▾]?\d*$/, "").trim() === name);
  function walk(steps, then, tries = 60) {
    if (!steps.length) return then?.();
    const b = probe()?.ready && row(steps[0]);
    if (!b) return tries > 0 && setTimeout(() => walk(steps, then, tries - 1), 150);
    b.click();
    setTimeout(() => walk(steps.slice(1), then), 900);
  }
  // a task is pointed at on its dot; the page replays CI events, so a dot can move between states, and the pointer follows
  // it (the page recomputes its hover each frame from the pointer). A click lands a frame after the pointer, as the page
  // reads the hover it drew; it is retried until the panel opens.
  function task(key, click, tries = 60) {
    const id = PICK[key], cv = document.querySelector("canvas");
    if (!id || !cv || !probe()?.ready || !target(id)) return tries > 0 && setTimeout(() => task(key, click, tries - 1), 150);
    let n = 0;
    const at = () => { const t = target(id), r = cv.getBoundingClientRect(); return t && { clientX: r.left + t.x, clientY: r.top + t.y, bubbles: true, view: window, button: 0 }; };
    const step = () => {
      const e = at();
      if (click && probe()?.panel) return cv.dispatchEvent(new MouseEvent("mousemove", { clientX: cv.getBoundingClientRect().left + 8, clientY: 8, bubbles: true, view: window }));
      if (!e || ++n > (click ? 20 : 60)) return;
      cv.dispatchEvent(new MouseEvent("mousemove", e));
      if (click) requestAnimationFrame(() => requestAnimationFrame(() => { cv.dispatchEvent(new MouseEvent("mousedown", e)); cv.dispatchEvent(new MouseEvent("mouseup", e)); }));
      setTimeout(step, click ? 400 : 200);
    };
    step();
  }

  {
    const p = new URLSearchParams(location.search);
    if (preset?.view) p.set("view", preset.view); else if (preset) p.delete("view");
    p.delete("s");
    try { window.history.replaceState(null, "", location.pathname + (p.toString() ? "?" + p : "")); } catch {}
  }
  document.addEventListener("DOMContentLoaded", () => {
    const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
    control();
    if (preset?.walk) setTimeout(() => walk(preset.walk, () => {
      if (preset.hover) setTimeout(() => task(preset.hover, false), 300);
      if (preset.click) setTimeout(() => task(preset.click, true), 300);
    }), 700);
  });
})();
