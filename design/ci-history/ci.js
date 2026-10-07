// Mockup layer: CI history in StarPulse, injected over a capture of the live page. The history is synthetic; the server
// that would record it does not exist yet.
// The operator's model (2026-10-06): each task carries its own CI status, readable at a glance; the Board states configured
// for GitHub (here In Progress and Review) are where it is shown. Detail is deferred until the user asks for it:
//   glance  - each task in a configured state shows its status the way the variant draws it (?v=<variant>)
//   hover   - a task's tooltip adds its checks: the push strip, what is failing and the counts
//   click   - a task's dot opens its panel with a CI summary; its history, a PR's pushes and a push's workflows each open
//             one click deeper
// Six variants to choose from (?v=): tag, glyph, callout, rail, all, ticker. Each pairs a Star Map treatment with a Kanban one.
// Definitions (operator interview): a run is one push (head commit) of a PR; re-runs (GitHub attempt > 1) and rebases
// (a push that rewrote the branch) are counted apart; conflicts are each time the PR turned CONFLICTING against main.
// The Kanban task modal is left alone until its two-column rework lands.
(() => {
  const STATES = {
    map: {},
    hover: { hover: "fail" },
    state: { drill: "in_progress" },
    panel: { panel: "fail" },
    "panel-multi": { panel: "multi" },
    "panel-clean": { panel: "clean" },
    kanban: { view: "kanban" },
  };
  const VARIANTS = {
    tag: "Name tags: problem tasks get a tag beside the dot; a status row on the card",
    glyph: "Glyph and id: a status badge and the id beside the dot; a coloured edge on the card",
    callout: "Callout stack: problem tasks listed beside their state with leader lines; the PR chip names the state",
    rail: "Side rail: one row per task at the canvas edge, hover links it to its dot; the card is tinted",
    all: "Tag every task: problems in full, green tasks as a dim tick; a status row on every card",
    ticker: "Ticker: one chip per problem task along the canvas foot; a bar across the card's top",
  };
  // the Board states whose config opts them into GitHub observability; the page draws CI only where the server sends it
  const GH = new Set(["in_progress", "review"]);
  const qs = new URLSearchParams(location.search);
  const preset = STATES[qs.get("s")] || null;
  const variant = VARIANTS[qs.get("v")] ? qs.get("v") : "tag";
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
      window.__CI = { CI, PICK, CAND, stat };
    },
  });

  // ---- a task's status now: only for a task in a configured state with an open PR ----
  const GLYPH = { fail: "✗", conflict: "⚠", pending: "◌", pass: "✓" };
  const RANK = { fail: 0, conflict: 1, pending: 2, pass: 3 };
  function stat(id) {
    const c = CI.get(id);
    if (!c || !GH.has(STATE[id]) || !c.prs.some((p) => !p.merged)) return null;
    const k = c.current in RANK ? c.current : "pass", p = c.head;
    const why = k === "fail" ? (p.pushes.at(-1).workflows.find((w) => w.outcome === "fail")?.name || "failing")
      : k === "conflict" ? "conflicts with main" : k === "pending" ? "running" : "green";
    return { id, k, g: GLYPH[k], why, pr: p.number, c };
  }
  const problem = (s) => s && s.k !== "pass";
  const ranked = () => [...CI.keys()].map(stat).filter(Boolean).sort((a, b) => RANK[a.k] - RANK[b.k] || a.id.localeCompare(b.id, undefined, { numeric: true }));
  const idIn = (el) => /DEMO-\d+(?!\d)/.exec(el?.textContent || "")?.[0];

  // ---- the Star Map: the capture's hooks report every task dot drawn this frame; the variant draws over them at the frame's end ----
  const POS = (window.__ciPOS = {});
  let SEEN = new Map(), HOT = null;
  const INK = "rgba(219,228,243,0.95)", MUTED = "rgba(148,163,184,0.95)", BG = "rgba(6,10,20,0.8)";
  window.__ci = {
    start() { SEEN = new Map(); },
    task(id, x, y, r, hot) { if (!SEEN.has(id)) { const s = stat(id); if (s) SEEN.set(id, { s, x, y, r, hot }); } },
    end(cx, K, labPx) {
      const m = cx.getTransform(), dpr = devicePixelRatio || 1, cv = cx.canvas.getBoundingClientRect();
      for (const k in POS) delete POS[k];
      for (const [id, d] of SEEN) POS[id] = { x: cv.left + (m.a * d.x + m.c * d.y + m.e) / dpr, y: cv.top + (m.b * d.x + m.d * d.y + m.f) / dpr, r: (d.r * m.a) / dpr };
      const u = 1 / K, fs = labPx(10.5), placed = [];
      cx.save();
      cx.textBaseline = "middle"; cx.textAlign = "left";
      const draw = { tag: drawTags, all: drawTags, glyph: drawGlyphs, callout: drawCallouts }[variant];
      if (draw) draw(cx, u, fs, placed);
      // a row hovered in the rail or the ticker lights its dot
      const h = HOT && SEEN.get(HOT);
      if (h) {
        cx.strokeStyle = COL[h.s.k]; cx.lineWidth = 1.6 * u;
        cx.beginPath(); cx.arc(h.x, h.y, h.r + 6 * u, 0, Math.PI * 2); cx.stroke();
      }
      cx.restore();
    },
  };
  // a box goes right of its dot, else left, else the nearest clear row above or below; the leader shows when it moved
  function place(placed, d, w, h, gap) {
    const hit = (x, y) => placed.some((b) => x < b.x + b.w && b.x < x + w && y < b.y + b.h && b.y < y + h);
    const R = d.x + d.r + gap, L = d.x - d.r - gap - w, y0 = d.y - h / 2;
    let at = null;
    for (let i = 0; i < 12 && !at; i++) {
      const dy = i === 0 ? 0 : Math.ceil(i / 2) * (h + 1) * (i % 2 ? 1 : -1);
      for (const x of [R, L]) if (!at && !hit(x, y0 + dy)) at = { x, y: y0 + dy };
    }
    at = at || { x: R, y: y0 };
    placed.push({ x: at.x, y: at.y, w, h });
    at.moved = at.y !== y0;
    at.left = at.x === L;
    return at;
  }
  function tie(cx, d, at, h, u, col = "rgba(148,163,184,.4)") {
    if (!at.moved) return;
    cx.strokeStyle = col; cx.lineWidth = 0.8 * u;
    cx.beginPath(); cx.moveTo(d.x + (at.left ? -d.r : d.r), d.y); cx.lineTo(at.left ? at.x + at.w : at.x, at.y + h / 2); cx.stroke();
  }
  function runs(cx, parts, x, y) {
    for (const [t, col, a = 1] of parts) { cx.globalAlpha = a; cx.fillStyle = col; cx.fillText(t, x, y); x += cx.measureText(t).width; }
    cx.globalAlpha = 1;
  }
  // tag and all: a tag beside the dot names the task and what is wrong; under all, a green task gets a dim tick too
  function drawTags(cx, u, fs, placed) {
    cx.font = `400 ${fs}px Inter, system-ui, sans-serif`;
    for (const [id, d] of SEEN) {
      const { s } = d, ok = !problem(s);
      if (ok && variant !== "all") continue;
      const parts = ok ? [[id, INK, 0.55], [` ${s.g}`, COL.pass, 0.6]] : [[`${s.g} `, COL[s.k]], [id, INK], [`  ${s.why}`, MUTED]];
      const w = parts.reduce((a, [t]) => a + cx.measureText(t).width, 0) + 8 * u, h = fs * 1.55;
      const at = place(placed, d, w, h, 4 * u); at.w = w;
      tie(cx, d, at, h, u);
      cx.fillStyle = BG; cx.beginPath(); cx.roundRect(at.x, at.y, w, h, 3 * u); cx.fill();
      runs(cx, parts, at.x + 4 * u, at.y + h / 2);
    }
  }
  // glyph: a filled status badge and the id beside the dot, no words
  function drawGlyphs(cx, u, fs, placed) {
    cx.font = `400 ${fs}px Inter, system-ui, sans-serif`;
    for (const [id, d] of SEEN) {
      const { s } = d;
      if (!problem(s)) continue;
      const R = fs * 0.62, h = Math.max(2 * R, fs * 1.4) + 2 * u, w = 2 * R + 4 * u + cx.measureText(id).width + 4 * u;
      const at = place(placed, d, w, h, 3 * u); at.w = w;
      tie(cx, d, at, h, u, COL[s.k]);
      cx.fillStyle = BG; cx.beginPath(); cx.roundRect(at.x, at.y, w, h, h / 2); cx.fill();
      const bx = at.x + R + 1 * u, by = at.y + h / 2;
      cx.fillStyle = COL[s.k]; cx.beginPath(); cx.arc(bx, by, R, 0, Math.PI * 2); cx.fill();
      cx.font = `700 ${fs * 0.85}px Inter, system-ui, sans-serif`; cx.textAlign = "center"; cx.fillStyle = "#0b1120";
      cx.fillText(s.g, bx, by + 0.5 * u);
      cx.font = `400 ${fs}px Inter, system-ui, sans-serif`; cx.textAlign = "left"; cx.fillStyle = INK;
      cx.fillText(id, bx + R + 4 * u, by);
    }
  }
  // callout: each state's problem tasks stacked in a column clear of its dots, every row tied to its dot by a leader line
  function drawCallouts(cx, u, fs, placed) {
    const by = {};
    for (const [id, d] of SEEN) if (problem(d.s)) (by[STATE[id]] = by[STATE[id]] || []).push(d);
    cx.font = `400 ${fs}px Inter, system-ui, sans-serif`;
    for (const ds of Object.values(by)) {
      ds.sort((a, b) => a.y - b.y);
      const all = [...SEEN.values()].filter((d) => STATE[d.s.id] === STATE[ds[0].s.id]);
      const x0 = Math.max(...all.map((d) => d.x + d.r)) + 34 * u, rh = fs * 1.7, my = ds.reduce((a, d) => a + d.y, 0) / ds.length;
      let y = my - (rh * ds.length) / 2;
      for (const d of ds) {
        const { s } = d, parts = [[`${s.g} `, COL[s.k]], [s.id, INK], [`  ${s.why}`, MUTED]];
        const w = parts.reduce((a, [t]) => a + cx.measureText(t).width, 0) + 8 * u;
        while (placed.some((b) => x0 < b.x + b.w && b.x < x0 + w && y < b.y + b.h && b.y < y + rh)) y += rh + 1;
        placed.push({ x: x0, y, w, h: rh });
        cx.strokeStyle = COL[s.k]; cx.globalAlpha = 0.5; cx.lineWidth = 0.9 * u;
        cx.beginPath(); cx.moveTo(d.x + d.r + 1.5 * u, d.y); cx.lineTo(x0 - 10 * u, y + rh / 2); cx.lineTo(x0 - 2 * u, y + rh / 2); cx.stroke();
        cx.globalAlpha = 1; cx.fillStyle = BG; cx.beginPath(); cx.roundRect(x0, y, w, rh, 3 * u); cx.fill();
        runs(cx, parts, x0 + 4 * u, y + rh / 2);
        y += rh + 1;
      }
    }
  }

  // ---- rail and ticker: DOM lists over the canvas; a row's hover lights its dot and draws its leader, its click opens the panel ----
  function list(kind) {
    let el = document.getElementById(`ci${kind}`);
    if (document.querySelector("#kb") || !document.querySelector("canvas")) return el && (el.hidden = true);
    const rows = ranked(), bad = rows.filter(problem), green = rows.filter((s) => !problem(s));
    const sig = rows.map((s) => s.id + s.k).join();
    if (!el) {
      el = Object.assign(document.createElement("div"), { id: `ci${kind}` });
      el.setAttribute("role", "list"); el.setAttribute("aria-label", "Checks by task");
      document.body.appendChild(el);
      el.addEventListener("mouseleave", () => { HOT = null; leader(); });
    }
    el.hidden = false;
    const cv = document.querySelector("canvas").getBoundingClientRect();
    // the visible map: the canvas less the side columns drawn over it
    const lx = Math.max(cv.left, document.getElementById("nav")?.getBoundingClientRect().right || 0);
    const rx = Math.min(cv.right, document.getElementById("rail")?.getBoundingClientRect().left || cv.right);
    if (kind === "rail") Object.assign(el.style, { left: `${lx + 16}px`, top: `${cv.bottom - 70 - el.offsetHeight}px` });
    else Object.assign(el.style, { left: `${(lx + rx) / 2}px`, top: `${cv.bottom - 64 - el.offsetHeight}px`, maxWidth: `${rx - lx - 48}px` });
    if (el.dataset.sig === sig) return;
    el.dataset.sig = sig;
    const row = (s) => `<div class="r ${s.k}" role="listitem" tabindex="0" data-id="${s.id}"><span class="cw ${s.k}">${s.g}</span><b>${esc(s.id)}</b><span class="why">${esc(s.why)}</span></div>`;
    el.innerHTML = kind === "rail"
      ? `<div class="h">checks</div>${bad.map(row).join("")}${green.length ? `<details><summary class="k g">✓ ${green.length} green</summary>${green.map(row).join("")}</details>` : ""}`
      : `${bad.map(row).join("")}${green.length ? `<span class="k g">✓ ${green.length} green</span>` : ""}`;
    el.querySelectorAll(".r").forEach((r) => {
      const id = r.dataset.id, on = () => { HOT = id; leader(); showPop(r, id); }, off = () => { HOT = null; leader(); hidePop(); };
      r.addEventListener("mouseenter", on); r.addEventListener("focus", on);
      r.addEventListener("mouseleave", off); r.addEventListener("blur", off);
      const go = () => { off(); openPanel(null, [id]); };
      r.addEventListener("click", go);
      r.addEventListener("keydown", (k) => { if (k.key === "Enter" || k.key === " ") { k.preventDefault(); go(); } });
    });
  }
  // the hovered row's leader: a thin line from the row to its dot, in screen space, kept on the dot while the map moves
  function leader() {
    let svg = document.getElementById("cilead");
    if (!svg) { svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.id = "cilead"; document.body.appendChild(svg); }
    const r = HOT && document.querySelector(`#cirail .r[data-id="${HOT}"], #citicker .r[data-id="${HOT}"]`), p = HOT && POS[HOT];
    if (!r || !p) return void (svg.innerHTML = "");
    const b = r.getBoundingClientRect(), s = stat(HOT), rail = r.closest("#cirail");
    const x1 = rail ? b.left - 4 : b.left + b.width / 2, y1 = rail ? b.top + b.height / 2 : b.top - 4;
    svg.innerHTML = `<path d="M${x1},${y1} L${p.x},${p.y}" stroke="${COL[s.k]}" stroke-width="1" stroke-dasharray="3 3" fill="none" opacity=".8"/>`;
  }
  const lists = () => { if (variant === "rail" || variant === "ticker") { list(variant); if (HOT) leader(); } };

  // ---- hover: a task's tooltip, and the floating pop for a Kanban mark or a list row, add its checks ----
  function detail(id) {
    const s = stat(id) || (CI.get(id) && { k: CI.get(id).current, c: CI.get(id), why: "", pr: CI.get(id).head.number });
    if (!s) return "";
    const c = s.c, fail = s.k === "fail" ? c.head.pushes.at(-1).workflows.find((w) => w.outcome === "fail") : null;
    return `<div class="citip"><div class="l1">${strip(c.prs.flatMap((p) => p.pushes).slice(-12))}<span class="cw ${s.k}">${word[s.k] || word[c.current]}</span>${fail ? `<span class="k">${esc(fail.name)} › ${esc(fail.step)}</span>` : ""}<span class="k">#${s.pr}</span></div><div class="k">${summary(c)}</div></div>`;
  }
  function showPop(el, id) {
    let pop = document.getElementById("cipop");
    if (!pop) { pop = Object.assign(document.createElement("div"), { id: "cipop" }); document.body.appendChild(pop); }
    pop.innerHTML = `<b>${esc(id)}</b> <span class="tt">${esc(CI.get(id)?.title || "")}</span>${detail(id)}<div class="k hint">click for the history</div>`;
    pop.hidden = false;
    const b = el.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
    pop.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, b.left))}px`;
    pop.style.top = `${b.bottom + h + 8 < innerHeight ? b.bottom + 6 : Math.max(8, b.top - h - 6)}px`;
  }
  function hidePop() { const p = document.getElementById("cipop"); if (p) p.hidden = true; }

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

  // ---- Kanban: each card in a configured state carries its own status, the variant's way ----
  function mark(card) {
    const s = stat(card.dataset.id);
    card.dataset.ci = s ? s.k : "";
    if (!s) return;
    const bad = problem(s), row = (cls = "") => Object.assign(document.createElement("div"), {
      className: `cirow ciel ${s.k} ${cls}`,
      innerHTML: `<span class="cw ${s.k}">${s.g}</span><span>${esc(bad ? s.why : "checks green")}</span><span class="k">#${s.pr}</span>`,
    });
    const t = card.querySelector(".t"), top = card.querySelector(".top");
    let el = null;
    if (variant === "tag" && bad) t.after((el = row()));
    else if (variant === "all") t.after((el = row(bad ? "" : "ok")));
    else if (variant === "rail" && bad) { card.classList.add("citint"); t.after((el = row())); }
    else if (variant === "glyph" && bad) {
      card.classList.add("ciedge");
      el = Object.assign(document.createElement("span"), { className: `ciglyph ciel ${s.k}`, textContent: s.g });
      top.prepend(el);
    } else if (variant === "callout" && bad) {
      const chip = top.querySelector(".pr");
      // the PR chip already on the card names its state: "#112 failing"
      el = Object.assign(document.createElement("span"), { className: `cichip ciel ${s.k}`, textContent: s.k === "fail" ? "failing" : s.k === "conflict" ? "conflict" : "running" });
      if (chip) { chip.classList.add("cion", s.k); chip.append(el); } else top.querySelector(".id").after(el);
    } else if (variant === "ticker" && bad) {
      card.classList.add("cibar");
      el = card;
    }
    if (!el) return;
    el.addEventListener("mouseenter", () => showPop(el === card ? card : el, s.id));
    el.addEventListener("mouseleave", hidePop);
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
  .citip { margin-top: 6px; padding-top: 6px; border-top: 1px solid rgba(148,163,184,.15); font-size: calc(11.5px * var(--fs)); }
  .citip .l1 { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; } .citip .k, #cipop .k { color: var(--muted); }
  #cipop { position: fixed; z-index: 30; max-width: 340px; padding: 8px 10px; border-radius: 8px; background: rgba(10,16,30,.98); border: 1px solid rgba(148,163,184,.22);
    box-shadow: 0 8px 24px rgba(0,0,0,.45); font: calc(12px * var(--fs)) Inter, system-ui, sans-serif; color: var(--ink); pointer-events: none; }
  #cipop b { font-family: "JetBrains Mono", ui-monospace, monospace; font-weight: 400; } #cipop .hint { margin-top: 4px; font-size: calc(10.5px * var(--fs)); }
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
  #kb .card .cirow { display: flex; gap: 6px; align-items: baseline; margin-top: 4px; font-size: calc(11.5px * var(--fs)); color: #cbd5e1; min-width: 0; }
  #kb .card .cirow > span:nth-child(2) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } #kb .card .cirow .k { color: var(--muted); margin-left: auto; }
  #kb .card .cirow.ok { opacity: .6; } #kb .card .cirow.ok > span:nth-child(2) { color: var(--muted); }
  #kb .card.ciedge[data-ci=fail] { box-shadow: inset 3px 0 0 ${COL.fail}; } #kb .card.ciedge[data-ci=conflict] { box-shadow: inset 3px 0 0 ${COL.conflict}; } #kb .card.ciedge[data-ci=pending] { box-shadow: inset 3px 0 0 ${COL.pending}; }
  #kb .card .ciglyph { font-weight: 700; margin-right: 4px; } #kb .card .ciglyph.fail { color: ${COL.fail}; } #kb .card .ciglyph.conflict { color: ${COL.conflict}; } #kb .card .ciglyph.pending { color: ${COL.pending}; }
  #kb .card .cichip { margin-left: 4px; white-space: nowrap; }
  #kb .card .pr.cion.fail { border-color: ${COL.fail}; } #kb .card .pr.cion.conflict { border-color: ${COL.conflict}; } #kb .card .pr.cion.pending { border-color: ${COL.pending}; }
  #kb .card .cichip.fail { color: ${COL.fail}; } #kb .card .cichip.conflict { color: ${COL.conflict}; } #kb .card .cichip.pending { color: ${COL.pending}; }
  #kb .card.citint[data-ci=fail] { background: rgba(251,113,133,.09); } #kb .card.citint[data-ci=conflict] { background: rgba(251,146,60,.09); } #kb .card.citint[data-ci=pending] { background: rgba(251,191,36,.07); }
  #kb .card.cibar[data-ci=fail] { box-shadow: inset 0 3px 0 ${COL.fail}; } #kb .card.cibar[data-ci=conflict] { box-shadow: inset 0 3px 0 ${COL.conflict}; } #kb .card.cibar[data-ci=pending] { box-shadow: inset 0 3px 0 ${COL.pending}; }
  #cirail, #citicker { position: fixed; z-index: 8; font: calc(12px * var(--fs)) Inter, system-ui, sans-serif; color: var(--ink); }
  #cirail { width: 240px; padding: 8px 10px; border-radius: 8px; background: rgba(10,16,30,.82); border: 1px solid rgba(148,163,184,.16); }
  #cirail .h { color: var(--muted); font-size: calc(10.5px * var(--fs)); letter-spacing: .08em; text-transform: uppercase; margin-bottom: 4px; }
  #cirail .r { display: grid; grid-template-columns: 14px auto minmax(0, 1fr); gap: 6px; align-items: baseline; padding: 2px 4px; margin: 0 -4px; border-radius: 4px; cursor: pointer; }
  #cirail .r .why { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #cirail summary { cursor: pointer; list-style: none; margin-top: 4px; } #cirail .k.g, #citicker .k.g { color: ${COL.pass}; opacity: .8; }
  #citicker { transform: translateX(-50%); display: flex; flex-wrap: wrap; justify-content: center; gap: 6px; align-items: center; }
  #citicker .r { display: flex; gap: 5px; align-items: baseline; padding: 3px 9px; border-radius: 12px; background: rgba(10,16,30,.85); border: 1px solid rgba(148,163,184,.2); cursor: pointer; }
  #citicker .r.fail { border-color: rgba(251,113,133,.45); } #citicker .r.conflict { border-color: rgba(251,146,60,.45); } #citicker .r.pending { border-color: rgba(251,191,36,.4); }
  #citicker .r .why { color: var(--muted); }
  #cirail .r b, #citicker .r b { font-family: "JetBrains Mono", ui-monospace, monospace; font-weight: 400; }
  #cirail .r:hover, #cirail .r:focus-visible, #citicker .r:hover, #citicker .r:focus-visible { background: rgba(148,163,184,.12); outline: none; }
  #cilead { position: fixed; inset: 0; width: 100vw; height: 100vh; pointer-events: none; z-index: 7; }
  #cimock { position: fixed; z-index: 9; left: 50%; bottom: 14px; transform: translateX(-50%); display: flex; gap: 6px; align-items: center; padding: 4px 6px 4px 10px; border-radius: 9px;
    background: rgba(12,19,34,.94); border: 1px dashed rgba(167,139,250,.6); font: 12px Inter, system-ui, sans-serif; color: #cbd5e1; }
  #cimock select { font: inherit; color: inherit; background: rgba(15,23,42,.9); border: 1px solid rgba(148,163,184,.25); border-radius: 6px; padding: 2px 4px; }
  `;

  // ---- wiring: observe the page and add the CI pieces wherever it draws a task's tooltip, its panel or its card ----
  function decorate() {
    const tip = document.getElementById("tip");
    if (tip && !tip.querySelector(".citip")) { const id = idIn(tip.querySelector(".n") || tip); if (id && stat(id)) tip.insertAdjacentHTML("beforeend", detail(id)); }
    const panel = document.getElementById("panel");
    if (panel && panel.querySelector("h2") && !panel.querySelector(".cipanel")) {
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
    for (const card of document.querySelectorAll("#kb .card[data-id]:not([data-ci])")) mark(card);
  }

  function control() {
    if (document.getElementById("cimock")) return;
    const bar = document.createElement("div");
    bar.id = "cimock";
    // the pickers reload into a variant and a preset, for viewers that cannot edit the address (an embedded copy)
    const s = qs.get("s") || "";
    bar.innerHTML = `<span>mockup</span><select aria-label="Variant">${Object.entries(VARIANTS).map(([k, t], i) => `<option value="${k}" title="${esc(t)}"${k === variant ? " selected" : ""}>${i + 1} · ${k}</option>`).join("")}</select>
      <select aria-label="Mockup state"><option value="">state…</option>${Object.keys(STATES).map((k) => `<option value="${k}"${k === s ? " selected" : ""}>${k}</option>`).join("")}</select>`;
    const [v, st] = bar.querySelectorAll("select");
    const go = () => { location.search = `?v=${v.value}${st.value ? `&s=${st.value}` : ""}`; };
    v.addEventListener("change", go); st.addEventListener("change", go);
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
  // point at a screen position the way a pointer does: hover, and a click when asked
  function pointer(p, click) {
    const cv = document.querySelector("canvas"), at = { clientX: p.x, clientY: p.y, bubbles: true, view: window };
    cv.dispatchEvent(new MouseEvent("mousemove", at));
    if (click) setTimeout(() => { cv.dispatchEvent(new MouseEvent("mousedown", { ...at, button: 0 })); cv.dispatchEvent(new MouseEvent("mouseup", { ...at, button: 0 })); }, 250);
  }
  function hoverTask(key, tries = 40) {
    const p = POS[PICK[key]];
    if (!p) return tries > 0 && setTimeout(() => hoverTask(key, tries - 1), 150);
    pointer(p, false);
  }
  function drill(state, tries = 40) {
    const g = window.flowProbe?.().states?.find?.((s) => s.id === state), cv = document.querySelector("canvas")?.getBoundingClientRect();
    if (!g || !cv) return tries > 0 && setTimeout(() => drill(state, tries - 1), 150);
    pointer({ x: cv.left + g.x, y: cv.top + g.y }, true);
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
    setInterval(lists, 200);
    if (preset?.panel) setTimeout(() => openPanel(preset.panel), 900);
    if (preset?.hover) setTimeout(() => hoverTask(preset.hover), 900);
    if (preset?.drill) setTimeout(() => drill(preset.drill), 900);
  });
})();
