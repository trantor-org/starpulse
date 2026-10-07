// Mockup layer: CI history in StarPulse, injected over a capture of the live page. The history is synthetic; the server
// that would record it does not exist yet.
// The operator's model (2026-10-06): CI belongs to the Board states configured for GitHub (here In Progress and Review),
// not to the dots; a dot is a cursor to a state. Detail is deferred until the user asks for it:
//   glance  - each configured state carries one CI line under its label, problems only ("✗ 2 failing · ⚠ 1 conflict"),
//             or "✓ checks green"; the Kanban column for the state carries the same line under its header
//   hover   - hovering the state (or that line on Kanban) lists the tasks behind each count
//   click   - a task's dot opens its panel with a CI summary; its history opens on a further click, a PR's pushes on
//             another, a push's workflows on another. Inside a state, a CHECKS caption repeats the line; click it for the PR list.
// Definitions (operator interview): a run is one push (head commit) of a PR; re-runs (GitHub attempt > 1) and rebases
// (a push that rewrote the branch) are counted apart; conflicts are each time the PR turned CONFLICTING against main.
// The Kanban task modal is left alone until its two-column rework lands.
(() => {
  const STATES = {
    map: {},
    "map-hover": { hover: "in_progress" },
    state: { drill: "in_progress" },
    panel: { panel: "fail" },
    "panel-multi": { panel: "multi" },
    "panel-clean": { panel: "clean" },
    kanban: { view: "kanban" },
  };
  // the Board states whose config opts them into GitHub observability; the page draws CI only where the server sends it
  const GH = new Set(["in_progress", "review"]);
  const qs = new URLSearchParams(location.search);
  const preset = STATES[qs.get("s")] || null;
  const COL = { pass: "#34d399", fail: "#fb7185", pending: "#fbbf24", cancelled: "#94a3b8", conflict: "#fb923c", merged: "#a78bfa", none: "#64748b" };
  const H = 3600;

  // ---- deterministic synthetic history, shaped on 24 merged trantor PRs: most one push and green, a long tail of rework ----
  const seed = (s) => { let h = 2166136261; for (const c of s) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return () => ((h = Math.imul(h ^ (h >>> 15), 2246822507) ^ Math.imul(h ^ (h >>> 13), 3266489909)) >>> 0) / 4294967296; };
  const hex = (rnd) => Array.from({ length: 7 }, () => "0123456789abcdef"[Math.floor(rnd() * 16)]).join("");
  const WORKFLOWS = ["CI", "Validate"];
  function history(id, pr, k, now, force) {
    const rnd = seed(`${id}#${k}`), roll = rnd();
    let n = roll < 0.66 ? 1 : roll < 0.86 ? 2 : roll < 0.95 ? 3 : roll < 0.985 ? 4 : 7;
    if (force?.pushes) n = force.pushes;
    const span = (2 + rnd() * 20) * H, end = pr.merged ? now - (6 + rnd() * 70) * H : now - rnd() * 0.6 * H;
    const pushes = [];
    for (let i = 0; i < n; i++) {
      const at = end - span + (span * (i + rnd() * 0.4)) / n, last = i === n - 1;
      let outcome = last ? (pr.merged || pr.checks === "pass" ? "pass" : pr.checks === "failing" ? "fail" : pr.checks === "pending" ? "pending" : "pass") : rnd() < 0.62 ? "fail" : rnd() < 0.5 ? "pass" : "cancelled";
      const failed = outcome === "fail" ? WORKFLOWS[Math.floor(rnd() * 2)] : null;
      const reruns = (force?.rerunAt === i) || (!force && outcome !== "pending" && rnd() < 0.08) ? 1 : 0;
      const rebase = i > 0 && ((force?.rebaseAt === i) || (!force && rnd() < 0.3));
      const workflows = WORKFLOWS.map((w) => ({
        name: w,
        attempts: w === "CI" ? 1 + reruns : 1,
        outcome: outcome === "pending" ? (w === "CI" ? "pending" : "pass") : outcome === "cancelled" ? "cancelled" : w === failed ? "fail" : reruns && w === "CI" ? "pass" : outcome === "fail" ? "pass" : "pass",
        took: Math.round((w === "CI" ? 240 : 95) * (0.7 + rnd() * 0.8)),
        step: w === failed ? (w === "CI" ? ["lint", "unit tests", "type check"][Math.floor(rnd() * 3)] : "validate config") : null,
      }));
      if (reruns) workflows[0].first = "fail";
      pushes.push({ at, sha: hex(rnd), outcome, reruns, rebase, workflows });
    }
    const conflicts = [];
    const cN = force?.conflicts ?? (n > 1 && rnd() < 0.3 ? 1 : 0);
    for (let c = 0; c < cN; c++) {
      const i = Math.min(n - 1, 1 + c), at = pushes[i].at - (0.3 + rnd()) * H;
      conflicts.push({ at, cleared: pushes[i].at });
      pushes[i].rebase = true;
    }
    let conflicting = false;
    if (force?.conflictNow) { conflicts.push({ at: now - 0.7 * H, cleared: null }); conflicting = true; }
    return { number: pr.number, url: pr.url, merged: pr.merged, current: pr.merged ? "merged" : conflicting ? "conflict" : pr.checks === "failing" ? "fail" : pr.checks, conflicting, pushes, conflicts };
  }
  function totals(prs) {
    const all = prs.flatMap((p) => p.pushes), open = prs.filter((p) => !p.merged), head = open[open.length - 1] || prs[prs.length - 1];
    const t = {
      prs, pushes: all.length, fails: all.filter((p) => p.outcome === "fail").length, reruns: all.reduce((s, p) => s + p.reruns, 0),
      rebases: all.filter((p) => p.rebase).length, conflicts: prs.reduce((s, p) => s + p.conflicts.length, 0),
      conflicting: prs.some((p) => p.conflicting), current: head.current, head,
    };
    t.story = t.current === "fail" || t.current === "pending" || t.conflicting || t.pushes > prs.length || t.reruns > 0 || t.rebases > 0 || t.conflicts > 0;
    return t;
  }
  // ---- formatting ----
  const ago = (s) => { const m = Math.max(0, Math.round(s / 60)); return m < 1 ? "now" : m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`; };
  const nowS = () => FX?.now || Date.now() / 1000;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const word = { pass: "passing", fail: "failing", pending: "running", merged: "merged", conflict: "conflicts with main", none: "no checks", cancelled: "cancelled" };
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : /(sh|ch|s|x)$/.test(w) ? "es" : "s"}`;
  const ICON = { push: "●", rerun: "↻", rebase: "⤴", conflict: "⚠" };
  const counts = (t, sep = " ") => [
    `<span title="${plural(t.pushes, "push")} across ${plural(t.prs.length, "PR")}">${t.pushes}×</span>`,
    t.reruns && `<span class="rr" title="${plural(t.reruns, "re-run")}">${ICON.rerun}${t.reruns}</span>`,
    t.rebases && `<span class="rb" title="${plural(t.rebases, "rebase")}">${ICON.rebase}${t.rebases}</span>`,
    t.conflicts && `<span class="cf${t.conflicting ? " now" : ""}" title="${plural(t.conflicts, "merge conflict")}${t.conflicting ? ", one open now" : ""}">${ICON.conflict}${t.conflicts}</span>`,
  ].filter(Boolean).join(sep);
  // one bar per push, coloured by its outcome; the last bar is the PR's state now
  const strip = (pushes, cls = "") => `<span class="cistrip ${cls}">${pushes.map((p, i) => `<i class="${p.outcome}${p.reruns ? " rr" : ""}${p.rebase ? " rb" : ""}${i === pushes.length - 1 ? " last" : ""}" title="${esc(p.sha)} · ${word[p.outcome]}${p.reruns ? " after a re-run" : ""}${p.rebase ? " · rebased" : ""}"></i>`).join("")}</span>`;
  function event(kind, at, html, cls = "") {
    return { at, html: `<div class="ev ${cls}"><span class="ic ${kind}">${ICON[kind] || "·"}</span><span class="tx">${html}</span><span class="ago">${ago(nowS() - at)}</span></div>` };
  }
  function prTimeline(p) {
    const evs = [];
    p.pushes.forEach((q, i) => {
      const fail = q.workflows.find((w) => w.outcome === "fail");
      const body = `<b class="sha">${esc(q.sha)}</b> ${i === 0 ? "opened" : q.rebase ? "rebased onto main" : "pushed"} · <span class="cw ${q.outcome}">${word[q.outcome]}</span>${fail ? ` <span class="k">${esc(fail.name)} › ${esc(fail.step)}</span>` : ""}
        <div class="wfs">${q.workflows.map((w) => `<div><span class="cw ${w.outcome}">${w.outcome === "pass" ? "✓" : w.outcome === "fail" ? "✗" : w.outcome === "pending" ? "◌" : "–"}</span> ${esc(w.name)}${w.step ? ` › ${esc(w.step)}` : ""}<span class="k"> · ${Math.floor(w.took / 60)}m ${w.took % 60}s${w.attempts > 1 ? ` · attempt ${w.attempts}, the first ${w.first === "fail" ? "failed" : "cancelled"}` : ""}</span></div>`).join("")}</div>`;
      evs.push(event(q.rebase && i ? "rebase" : "push", q.at, body, `push ${q.outcome}`));
      if (q.reruns) evs.push(event("rerun", q.at + 420, `re-ran <b>CI</b> on <b class="sha">${esc(q.sha)}</b> · <span class="cw pass">passing</span>`));
    });
    for (const c of p.conflicts) {
      evs.push(event("conflict", c.at, `conflicted with main${c.cleared ? "" : " · <b>open</b>"}`, c.cleared ? "" : "open"));
      if (c.cleared) evs.push(event("conflict", c.cleared, `conflict cleared by a rebase`, "cleared"));
    }
    return evs.sort((a, b) => b.at - a.at).map((e) => e.html).join("");
  }

  // ---- intercept the capture's fixture: give the configured states the open PRs a live board would show, then derive every task's history ----
  const CI = new Map(), PICK = {}, CAND = {}, STATE = {}, NAME = {};
  let FX;
  Object.defineProperty(window, "__FLOW_FIXTURE__", {
    configurable: true,
    get: () => FX,
    set(fx) {
      FX = fx;
      const flow = (fx.flows || []).find((f) => f.name === "board"), board = flow?.agents || [];
      for (const s of flow?.machine?.states || []) NAME[s.name] = s.id;
      const pulls = (fx.pulls = fx.pulls || {});
      const now = fx.now || Date.now() / 1000;
      const openPr = (a) => pulls[a.id]?.some((p) => !p.merged);
      const free = (state) => board.find((a) => a.state === state && !pulls[a.id] && !Object.values(PICK).includes(a.id));
      const force = {};
      // In Progress: two failing (one with a long story), one running, two green; Review: the PRs it holds, one gone conflicting
      const want = [["fail", "failing", { pushes: 4, rerunAt: 1, rebaseAt: 2, conflicts: 1 }], ["fail2", "failing", { pushes: 2 }],
        ["pending", "pending", { pushes: 2 }], ["green", "pass", { pushes: 3, rebaseAt: 1 }], ["green2", "pass", { pushes: 1 }]];
      for (const [key, checks, f] of want) {
        const a = free("in_progress");
        if (!a) continue;
        pulls[a.id] = [{ number: 0, url: "#", checks, merged: false, threads: 0, stale: false }];
        PICK[key] = a.id; force[a.id] = f;
      }
      // the live board may hold nothing in Review; move two In Progress tasks along so the mockup shows that state's line
      for (let k = board.filter((a) => a.state === "review").length; k < 2; k++) { const a = free("in_progress"); if (a) a.state = "review"; }
      const rev = board.filter((a) => a.state === "review" && openPr(a));
      for (const a of board.filter((x) => x.state === "review" && !openPr(x)).slice(0, Math.max(0, 2 - rev.length))) {
        (pulls[a.id] = pulls[a.id] || []).push({ number: 0, url: "#", checks: "pass", merged: false, threads: 0, stale: false });
        rev.push(a);
      }
      if (rev[0]) { PICK.conflict = rev[0].id; force[rev[0].id] = { pushes: 3, conflictNow: true, rebaseAt: 1 }; }
      // the scrubbed capture repeats a task's PR number and drops each task's PR links; number every PR once and link it back
      let n = 100;
      for (const a of board) for (const p of pulls[a.id] || []) { p.number = n++; p.url = `#pull/${p.number}`; }
      for (const a of board) {
        STATE[a.id] = a.state;
        const ps = pulls[a.id];
        if (!ps?.length) continue;
        a.prs = ps.map((p) => p.url);
        CI.set(a.id, totals(ps.map((p, k) => history(a.id, p, k, now, k === ps.length - 1 ? force[a.id] : null))));
        CI.get(a.id).title = a.title || "";
      }
      const multi = [...CI].filter(([, t]) => t.prs.length >= 3 && t.story);
      CAND.multi = (multi.length ? multi : [...CI].filter(([, t]) => t.prs.length >= 2)).map(([id]) => id);
      CAND.clean = [...CI].filter(([, t]) => !t.story && t.prs.length === 1).map(([id]) => id);
      CAND.fail = [PICK.fail];
      PICK.multi = CAND.multi[0]; PICK.clean = CAND.clean[0];
      window.__CI = { CI, PICK, CAND, buckets };
    },
  });

  // a configured state's open PRs, by what each asks of the user now
  function buckets(state) {
    const b = { fail: [], conflict: [], pending: [], pass: [] };
    if (!GH.has(state)) return b;
    for (const [id, c] of CI) {
      if (STATE[id] !== state || !c.prs.some((p) => !p.merged)) continue;
      (b[c.current] || b.pass).push(id);
    }
    return b;
  }
  const BUCKET = [["fail", "✗", (n) => `${n} failing`], ["conflict", "⚠", (n) => `${n} conflict${n === 1 ? "" : "s"}`], ["pending", "◌", (n) => `${n} running`]];
  // the glance line: problems only, worst first; a state with open PRs and no problem says so once
  function glance(b) {
    const segs = BUCKET.filter(([k]) => b[k].length).map(([k, g, w]) => ({ k, t: `${g} ${w(b[k].length)}` }));
    return segs.length ? segs : b.pass.length ? [{ k: "pass", t: "✓ checks green" }] : [];
  }

  // ---- the state's CI line on the Star Map, drawn by the capture's hook under a galaxy's label ----
  const POS = (window.__ciPOS = {});
  window.__ciState = (cx, name, x, y, size, hot, K, bx, by) => {
    const id = NAME[name];
    if (!GH.has(id)) return;
    const m = cx.getTransform(), dpr = devicePixelRatio || 1, cv = cx.canvas.getBoundingClientRect();
    POS[id] = { x: cv.left + (m.a * bx + m.c * by + m.e) / dpr, y: cv.top + (m.b * bx + m.d * by + m.f) / dpr };
    const segs = glance(buckets(id));
    if (!segs.length) return;
    cx.save();
    cx.font = `400 ${size}px Inter, system-ui, sans-serif`;
    cx.textBaseline = "middle"; cx.textAlign = "left";
    const gap = size * 0.9, w = segs.map((s) => cx.measureText(s.t).width), total = w.reduce((a, b) => a + b, 0) + gap * (segs.length - 1);
    let at = x - total / 2;
    segs.forEach((s, i) => {
      cx.fillStyle = COL[s.k]; cx.globalAlpha = s.k === "pass" ? (hot ? 0.8 : 0.55) : hot ? 1 : 0.9;
      cx.fillText(s.t, at, y);
      at += w[i] + gap;
    });
    cx.restore();
  };

  // ---- hover: the state's tooltip lists the tasks behind each count ----
  const idIn = (el) => /DEMO-\d+(?!\d)/.exec(el?.textContent || "")?.[0];
  function taskRow(id, k) {
    const c = CI.get(id), p = c.head;
    const why = k === "fail" ? (p.pushes.at(-1).workflows.find((w) => w.outcome === "fail")?.name || "") : k === "conflict" ? "conflicts with main" : k === "pending" ? "checks running" : "";
    return `<div class="r"><span class="cw ${k}">${{ fail: "✗", conflict: "⚠", pending: "◌", pass: "✓" }[k]}</span><b>${esc(id)}</b><span class="tt">${esc(c.title)}</span><span class="k">#${p.number}${why ? ` · ${esc(why)}` : ""}</span></div>`;
  }
  function stateList(state, max = 6) {
    const b = buckets(state), rows = [];
    for (const [k] of BUCKET) for (const id of b[k]) rows.push(taskRow(id, k));
    const more = rows.length > max ? `<div class="k">+${rows.length - max} more</div>` : "";
    const green = b.pass.length ? `<div class="k g">✓ ${plural(b.pass.length, "PR")} green</div>` : "";
    return rows.length || green ? `${rows.slice(0, max).join("")}${more}${green}` : `<div class="k">no open pull requests</div>`;
  }
  function tipState(tip) {
    if (tip.querySelector(".cistate")) return;
    const k = tip.querySelector(".k")?.textContent || "", id = NAME[tip.querySelector(".n")?.textContent || ""];
    if (!k.startsWith("Board state") || !GH.has(id)) return;
    tip.insertAdjacentHTML("beforeend", `<div class="cistate"><div class="h">checks on its pull requests${k.includes("click to open") ? "" : " · click for the list"}</div>${stateList(id)}</div>`);
  }

  // ---- click: a task's panel carries its CI summary, with each further level of history one click deeper ----
  function summary(c) {
    if (!c.story) return "green on its first push";
    return [plural(c.pushes, "push"), c.fails && `${c.fails} failed`, c.reruns && plural(c.reruns, "re-run"), c.rebases && plural(c.rebases, "rebase"), c.conflicts && plural(c.conflicts, "conflict")].filter(Boolean).join(" · ");
  }
  function panelBlock(id) {
    const c = CI.get(id);
    const prs = c.prs.slice().reverse();
    const prBody = (p) => `<div class="tl">${prTimeline(p)}</div>`;
    const hist = prs.length === 1 ? prBody(prs[0])
      : prs.map((p) => `<details class="cipr"><summary><a href="${esc(p.url)}" onclick="event.stopPropagation()">#${p.number}</a>${strip(p.pushes)}<span class="cw ${p.current}">${word[p.current]}</span><span class="k">${plural(p.pushes.length, "push")}</span></summary>${prBody(p)}</details>`).join("");
    return `<div class="cipanel">
      <div class="cih"><b>Checks</b><span class="cw ${c.current}">${word[c.current]}</span>${strip(c.prs.flatMap((p) => p.pushes).slice(-12))}</div>
      <div class="cis">${summary(c)}</div>
      ${c.conflicting ? `<div class="cinote cf">⚠ #${c.head.number} conflicts with main since ${ago(nowS() - c.head.conflicts.at(-1).at)} ago</div>` : ""}
      <details class="cihist"><summary>History${prs.length > 1 ? ` · ${plural(prs.length, "pull request")}` : ` · #${prs[0].number}`}</summary>${hist}</details>
    </div>`;
  }
  // on a configured state's own level, clicking the state opens its PR list; a row opens that task's panel
  function statePanel(state) {
    const panel = document.getElementById("panel");
    const name = Object.keys(NAME).find((n) => NAME[n] === state);
    panel.innerHTML = `<span class="x">✕</span><div class="k">Board state · checks on its pull requests</div><h2>${esc(name)}</h2><div class="cistate inpanel">${stateList(state, 99)}</div>`;
    panel.classList.add("open");
    panel.querySelector(".x").addEventListener("click", () => panel.classList.remove("open"));
    panel.querySelectorAll(".cistate .r").forEach((r) => {
      Object.assign(r, { tabIndex: 0 }); r.setAttribute("role", "button");
      const go = () => openPanel(null, [idIn(r)]);
      r.addEventListener("click", go);
      r.addEventListener("keydown", (k) => { if (k.key === "Enter" || k.key === " ") { k.preventDefault(); go(); } });
    });
  }
  // on a configured state's own level, a caption over the canvas carries the same line; hover lists, click opens the list as a panel
  function caption() {
    const at = window.flowProbe?.().path.split("/"), state = at?.length === 2 ? at[1] : null;
    let cap = document.getElementById("cicap");
    if (!GH.has(state) || document.querySelector("#kb")) return cap && cap.remove();
    if (cap?.dataset.state === state) return;
    cap?.remove();
    const segs = glance(buckets(state));
    if (!segs.length) return;
    cap = Object.assign(document.createElement("div"), { id: "cicap", tabIndex: 0 });
    cap.dataset.state = state;
    cap.setAttribute("role", "button");
    cap.setAttribute("aria-label", `Checks: ${segs.map((x) => x.t.slice(2)).join(", ")}. Open the list`);
    cap.innerHTML = `<span class="h">checks</span>${segs.map((x) => `<span class="cw ${x.k}">${x.t}</span>`).join("")}<div class="pop"><div class="cistate">${stateList(state)}</div></div>`;
    const cv = document.querySelector("canvas").getBoundingClientRect();
    cap.style.left = `${cv.left + cv.width / 2}px`;
    cap.addEventListener("click", () => { cap.blur(); statePanel(state); });
    cap.addEventListener("keydown", (k) => { if (k.key === "Enter" || k.key === " ") { k.preventDefault(); statePanel(state); } });
    document.body.appendChild(cap);
  }
  setInterval(caption, 250);

  // ---- Kanban: the configured state's column carries the same line under its header; hovering it lists the tasks ----
  function columnLine(col) {
    const state = col.dataset.lane, segs = glance(buckets(state));
    const d = document.createElement("div");
    d.className = "cicol";
    if (!segs.length) { d.hidden = true; return d; }
    d.tabIndex = 0;
    d.setAttribute("aria-label", `Checks: ${segs.map((s) => s.t.slice(2)).join(", ")}`);
    d.innerHTML = `${segs.map((s) => `<span class="cw ${s.k}">${s.t}</span>`).join("")}<div class="pop"><div class="cistate">${stateList(state, 99)}</div></div>`;
    d.querySelectorAll(".pop .r").forEach((r) => r.addEventListener("click", () => {
      const card = document.querySelector(`#kb .card[data-id="${idIn(r)}"]`);
      if (!card) return;
      card.scrollIntoView({ block: "center", behavior: "smooth" });
      card.classList.add("ciflash"); setTimeout(() => card.classList.remove("ciflash"), 1600);
      d.blur();
    }));
    return d;
  }

  // ---- styles ----
  const css = `
  .cistrip { display: inline-flex; gap: 1.5px; align-items: flex-end; vertical-align: middle; }
  .cistrip i { width: 3px; height: 9px; border-radius: 1px; background: ${COL.none}; }
  .cistrip i.pass { background: ${COL.pass}; } .cistrip i.fail { background: ${COL.fail}; } .cistrip i.cancelled { background: ${COL.cancelled}; opacity: .55; }
  .cistrip i.pending { background: ${COL.pending}; animation: cipulse 1.4s ease-in-out infinite; }
  @keyframes cipulse { 50% { opacity: .35; } }
  @media (prefers-reduced-motion: reduce) { .cistrip i.pending { animation: none; } }
  .cw { white-space: nowrap; }
  .cw.pass { color: ${COL.pass}; } .cw.fail { color: ${COL.fail}; } .cw.pending { color: ${COL.pending}; } .cw.merged { color: ${COL.merged}; } .cw.conflict { color: ${COL.conflict}; } .cw.cancelled, .cw.none { color: ${COL.cancelled}; }
  .cistate { margin-top: 6px; padding-top: 6px; border-top: 1px solid rgba(148,163,184,.15); font-size: calc(11.5px * var(--fs)); max-width: 340px; }
  .cistate .h { color: var(--muted); font-size: calc(10.5px * var(--fs)); margin-bottom: 3px; }
  .cistate .r { display: grid; grid-template-columns: 14px auto minmax(0, 1fr) auto; gap: 6px; align-items: baseline; padding: 1px 0; }
  .cistate .r b { font-family: "JetBrains Mono", ui-monospace, monospace; font-weight: 400; color: #cbd5e1; }
  .cistate .r .tt { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink); }
  .cistate .k { color: var(--muted); } .cistate .k.g { color: ${COL.pass}; opacity: .8; margin-top: 2px; }
  #panel .cistate.inpanel { border: 0; max-width: none; } #panel .cistate.inpanel .r { cursor: pointer; padding: 4px 2px; border-radius: 4px; }
  #panel .cistate.inpanel .r:hover, #panel .cistate.inpanel .r:focus-visible { background: rgba(148,163,184,.08); outline: none; }
  .cipanel { margin: 10px 0 6px; padding-top: 8px; border-top: 1px solid rgba(148,163,184,.15); font-size: calc(12px * var(--fs)); }
  .cih { display: flex; gap: 8px; align-items: center; } .cih b { font-weight: 500; }
  .cis { color: var(--muted); margin: 3px 0 0; font-size: calc(11.5px * var(--fs)); }
  .cinote { margin-top: 4px; font-size: calc(11.5px * var(--fs)); } .cinote.cf { color: ${COL.conflict}; }
  .cipanel details > summary { cursor: pointer; color: #94a3b8; font-size: calc(11.5px * var(--fs)); list-style: none; display: flex; gap: 6px; align-items: center; }
  .cipanel details > summary::before { content: "▸"; color: var(--muted); } .cipanel details[open] > summary::before { content: "▾"; }
  .cipanel details > summary:focus-visible { outline: 1px solid #a78bfa; outline-offset: 2px; border-radius: 3px; }
  .cihist { margin-top: 8px; } .cipr { margin: 4px 0 0 12px; } .cipr summary .k { margin-left: auto; color: var(--muted); }
  .cipanel .tl { margin: 6px 0 2px 4px; border-left: 1px solid rgba(148,163,184,.2); padding-left: 10px; }
  .cipanel .ev { display: grid; grid-template-columns: 14px 1fr auto; gap: 6px; align-items: baseline; padding: 2px 0; font-size: calc(11.5px * var(--fs)); }
  .cipanel .ev.push { cursor: pointer; } .cipanel .ev .wfs { display: none; margin: 3px 0 2px; color: #cbd5e1; } .cipanel .ev.open .wfs { display: block; }
  .cipanel .ev .ic { text-align: center; color: #94a3b8; } .cipanel .ev .ic.conflict { color: ${COL.conflict}; }
  .cipanel .ev.push.fail .ic { color: ${COL.fail}; } .cipanel .ev.push.pass .ic { color: ${COL.pass}; } .cipanel .ev.push.pending .ic { color: ${COL.pending}; }
  .cipanel .ev.push:focus-visible { outline: 1px solid #a78bfa; outline-offset: 1px; border-radius: 4px; } .cipanel .ev .ago { color: var(--muted); font-size: calc(10.5px * var(--fs)); }
  .cipanel .ev .sha { font-family: "JetBrains Mono", ui-monospace, monospace; font-weight: 400; color: #cbd5e1; } .cipanel .ev .k { color: var(--muted); }
  #kb .col .cicol { position: relative; display: flex; flex-wrap: wrap; gap: 4px 10px; padding: 0 12px 8px; font-size: calc(11.5px * var(--fs)); cursor: default; }
  #kb .col .cicol:focus-visible { outline: 1px solid #a78bfa; outline-offset: -2px; border-radius: 4px; }
  #kb .col .cicol .pop { display: none; position: absolute; z-index: 20; top: 100%; left: 8px; width: min(340px, calc(100vw - 32px)); padding: 8px 10px; border-radius: 8px; background: rgba(10,16,30,.98); border: 1px solid rgba(148,163,184,.22); box-shadow: 0 8px 24px rgba(0,0,0,.45); }
  #kb .col .cicol:hover .pop, #kb .col .cicol:focus-within .pop { display: block; }
  #kb .col .cicol .pop .cistate, #kb .col .cicol .pop { max-width: none; } #kb .col .cicol .pop .r { cursor: pointer; } #kb .col .cicol .pop .r:hover .tt { text-decoration: underline; }
  #cicap { position: fixed; z-index: 8; top: 64px; transform: translateX(-50%); display: flex; gap: 10px; align-items: center; padding: 5px 12px; border-radius: 8px; cursor: pointer;
    background: rgba(10,16,30,.85); border: 1px solid rgba(148,163,184,.16); font: calc(12px * var(--fs)) Inter, system-ui, sans-serif; }
  #cicap .h { color: var(--muted); font-size: calc(10.5px * var(--fs)); letter-spacing: .08em; text-transform: uppercase; }
  #cicap:hover, #cicap:focus-visible { border-color: rgba(167,139,250,.6); outline: none; }
  #cicap .pop { display: none; position: absolute; top: calc(100% + 6px); left: 50%; transform: translateX(-50%); width: 340px; padding: 8px 10px; border-radius: 8px; background: rgba(10,16,30,.98); border: 1px solid rgba(148,163,184,.22); box-shadow: 0 8px 24px rgba(0,0,0,.45); cursor: default; }
  #cicap:hover .pop { display: block; } #cicap .pop .r { cursor: default; }
  .pop .cistate { border: 0; margin: 0; padding: 0; max-width: none; }
  #kb .card.ciflash { outline: 1px solid #a78bfa; outline-offset: 1px; transition: outline-color 1.6s; }
  #cimock { position: fixed; z-index: 9; left: 50%; bottom: 14px; transform: translateX(-50%); display: flex; gap: 6px; align-items: center; padding: 4px 6px 4px 10px; border-radius: 9px;
    background: rgba(12,19,34,.94); border: 1px dashed rgba(167,139,250,.6); font: 12px Inter, system-ui, sans-serif; color: #cbd5e1; }
  #cimock select { font: inherit; color: inherit; background: rgba(15,23,42,.9); border: 1px solid rgba(148,163,184,.25); border-radius: 6px; padding: 2px 4px; }
  `;

  // ---- wiring: observe the page and add the CI pieces wherever it draws a configured state or a task's panel ----
  function decorate() {
    const tip = document.getElementById("tip");
    if (tip) tipState(tip);
    const panel = document.getElementById("panel");
    if (panel && panel.querySelector("h2") && !panel.querySelector(".cipanel, .cistate")) {
      const id = idIn(panel.querySelector("h2"));
      const table = panel.querySelector(":scope > table");
      // a Board task's panel only; a machine task's reads "task · <flow> · <state>"
      if (id && CI.has(id) && table && (panel.querySelector(".k")?.textContent || "").startsWith("task · click")) {
        table.insertAdjacentHTML("afterend", panelBlock(id));
        // a push row is a toggle: the pointer or Enter/Space opens its workflows
        panel.querySelectorAll(".cipanel .ev.push").forEach((e) => {
          const flip = () => e.setAttribute("aria-expanded", e.classList.toggle("open"));
          Object.assign(e, { tabIndex: 0 }); e.setAttribute("role", "button"); e.setAttribute("aria-expanded", "false");
          e.addEventListener("click", flip);
          e.addEventListener("keydown", (k) => { if (k.key === "Enter" || k.key === " ") { k.preventDefault(); flip(); } });
        });
      }
    }
    for (const col of document.querySelectorAll("#kb section.col[data-lane]")) {
      if (!GH.has(col.dataset.lane) || col.querySelector(":scope > .cicol")) continue;
      col.querySelector(":scope > h2")?.after(columnLine(col));
    }
  }

  function control() {
    if (document.getElementById("cimock")) return;
    const bar = document.createElement("div");
    bar.id = "cimock";
    // the state picker reloads into a preset, for viewers that cannot edit the address (an embedded copy)
    bar.innerHTML = `<span>mockup</span><select aria-label="Mockup state"><option value="">state…</option>${Object.keys(STATES).map((k) => `<option value="${k}">${k}</option>`).join("")}</select>`;
    bar.querySelector("select").addEventListener("change", (e) => { if (e.target.value) location.search = `?s=${e.target.value}`; });
    document.body.appendChild(bar);
  }

  // open the preset's Star Map panel the way a user finds a task: type its id into the search box and take the first match;
  // a candidate whose id is a prefix of another's may land on the other, so the next candidate is tried
  function openPanel(key, order = null, tries = 40) {
    order = order ?? [PICK[key], ...(CAND[key] || [])].filter((v, i, a) => v && a.indexOf(v) === i);
    const q = document.getElementById("q"), id = order[0];
    if (!q || !id || !document.querySelector("canvas")) return tries > 0 && setTimeout(() => openPanel(key, order, tries - 1), 150);
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(q, id);
    q.dispatchEvent(new Event("input", { bubbles: true }));
    setTimeout(() => {
      q.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      setTimeout(() => {
        if (idIn(document.querySelector("#panel.open h2")) === id) return key && void (PICK[key] = id);
        if (tries > 0) openPanel(key, order.length > 1 && idIn(document.querySelector("#panel.open h2")) ? order.slice(1) : order, tries - 1);
      }, 300);
    }, 100);
  }
  // hover or open a configured state's galaxy the way a pointer does, at the point its hook last drew it
  function pointAt(state, click, tries = 40) {
    const p = POS[state], cv = document.querySelector("canvas");
    if (!p || !cv) return tries > 0 && setTimeout(() => pointAt(state, click, tries - 1), 150);
    const at = { clientX: p.x, clientY: p.y, bubbles: true, view: window };
    cv.dispatchEvent(new MouseEvent("mousemove", at));
    if (click) setTimeout(() => { cv.dispatchEvent(new MouseEvent("mousedown", { ...at, button: 0 })); cv.dispatchEvent(new MouseEvent("mouseup", { ...at, button: 0 })); }, 250);
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
    new MutationObserver(decorate).observe(document.body, { childList: true, subtree: true, characterData: true });
    decorate();
    if (preset?.panel) setTimeout(() => openPanel(preset.panel), 900);
    if (preset?.hover) setTimeout(() => pointAt(preset.hover, false), 900);
    if (preset?.drill) setTimeout(() => pointAt(preset.drill, true), 900);
  });
})();
