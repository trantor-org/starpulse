// Mockup layer: a task's CI history on the Star Map dot and task panel and on the Kanban card and task modal,
// injected over a capture of the live page. The history is synthetic; the server that would record it does not exist yet.
// Definitions (operator interview): a run is one push (head commit) of a PR; re-runs (GitHub attempt > 1) and rebases
// (a push that rewrote the branch) are counted apart; conflicts are each time the PR turned CONFLICTING against main.
// A dot carries a mark only when there is a story: checks failing or pending now, more than one push, a re-run, a
// rebase or a conflict. A task with several PRs shows its total, with each PR broken out in the panel and modal.
(() => {
  const STATES = {
    map: {},
    "map-panel": { panel: "fail" },
    "map-multi": { panel: "multi" },
    "map-clean": { panel: "clean" },
    kanban: { view: "kanban" },
    modal: { view: "kanban", modal: "fail" },
    "modal-conflict": { view: "kanban", modal: "conflict" },
    "modal-multi": { view: "kanban", modal: "multi" },
  };
  const qs = new URLSearchParams(location.search);
  const preset = STATES[qs.get("s")] || null;
  const MARKS = ["ring", "pip", "tag"];
  let mark = MARKS.includes(qs.get("mark")) ? qs.get("mark") : "ring";
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

  // ---- intercept the capture's fixture: give a few open tasks the open PRs a live board would show, then derive every task's history ----
  const CI = new Map(), PICK = {}, CAND = {};
  let FX;
  Object.defineProperty(window, "__FLOW_FIXTURE__", {
    configurable: true,
    get: () => FX,
    set(fx) {
      FX = fx;
      const board = (fx.flows || []).find((f) => f.name === "board")?.agents || [];
      const pulls = (fx.pulls = fx.pulls || {});
      const now = fx.now || Date.now() / 1000;
      let num = 9000;
      const open = (state, checks) => board.find((a) => a.state === state && !pulls[a.id] && !Object.values(PICK).includes(a.id) && (pulls[a.id] = [{ number: num++, url: "#", checks, merged: false, threads: 0, stale: false }]));
      // open PRs on the tasks that would hold them: Review and a few In Progress, one per story the mockup must show
      const force = {};
      const want = [["fail", "in_progress", "failing", { pushes: 4, rerunAt: 1, rebaseAt: 2, conflicts: 1 }], ["pending", "in_progress", "pending", { pushes: 2 }],
        ["conflict", "in_progress", "pass", { pushes: 3, conflictNow: true, rebaseAt: 1 }], ["rerun", "review", "pass", { pushes: 1, rerunAt: 0 }]];
      for (const [key, state, checks, f] of want) {
        const held = key === "rerun" && board.find((x) => x.state === state && pulls[x.id]?.some((p) => !p.merged));
        const a = held || open(state, checks);
        if (a) { PICK[key] = a.id; force[a.id] = f; }
      }
      // the scrubbed capture repeats a task's PR number and drops each task's PR links; number every PR once and link it back
      // from its task, so the page's own "Pull request" row and the CI block name the same PRs
      let n = 100;
      for (const a of board) for (const p of pulls[a.id] || []) { p.number = n++; p.url = `#pull/${p.number}`; }
      for (const a of board) {
        const ps = pulls[a.id];
        if (!ps?.length) continue;
        a.prs = ps.map((p) => p.url);
        CI.set(a.id, totals(ps.map((p, k) => history(a.id, p, k, now, k === ps.length - 1 ? force[a.id] : null))));
      }
      // the panel and modal presets: the forced stories, a task with several PRs, and a clean one-shot task
      const multi = [...CI].filter(([, t]) => t.prs.length >= 3 && t.story);
      CAND.multi = (multi.length ? multi : [...CI].filter(([, t]) => t.prs.length >= 2)).map(([id]) => id);
      CAND.clean = [...CI].filter(([, t]) => !t.story && t.prs.length === 1).map(([id]) => id);
      PICK.multi = CAND.multi[0]; PICK.clean = CAND.clean[0];
      window.__CI = { CI, PICK, CAND };
    },
  });

  // ---- formatting ----
  const ago = (s) => { const m = Math.max(0, Math.round(s / 60)); return m < 1 ? "now" : m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`; };
  const nowS = () => FX?.now || Date.now() / 1000;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const word = { pass: "passing", fail: "failing", pending: "running", merged: "merged", conflict: "conflicts with main", none: "no checks", cancelled: "cancelled" };
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const ICON = { push: "●", rerun: "↻", rebase: "⤴", conflict: "⚠" };
  const counts = (t, sep = " ") => [
    `<span title="${plural(t.pushes, "push")} across ${plural(t.prs.length, "PR")}">${t.pushes}×</span>`,
    t.reruns && `<span class="rr" title="${plural(t.reruns, "re-run")}">${ICON.rerun}${t.reruns}</span>`,
    t.rebases && `<span class="rb" title="${plural(t.rebases, "rebase")}">${ICON.rebase}${t.rebases}</span>`,
    t.conflicts && `<span class="cf${t.conflicting ? " now" : ""}" title="${plural(t.conflicts, "merge conflict")}${t.conflicting ? ", one open now" : ""}">${ICON.conflict}${t.conflicts}</span>`,
  ].filter(Boolean).join(sep);
  // one bar per push, coloured by its outcome; the last bar is the PR's state now
  const strip = (pushes, cls = "") => `<span class="cistrip ${cls}">${pushes.map((p, i) => `<i class="${p.outcome}${p.reruns ? " rr" : ""}${p.rebase ? " rb" : ""}${i === pushes.length - 1 ? " last" : ""}" title="${esc(p.sha)} · ${word[p.outcome]}${p.reruns ? " after a re-run" : ""}${p.rebase ? " · rebased" : ""}"></i>`).join("")}</span>`;

  // ---- the Star Map dot mark, drawn by the capture's hook in drawTasks ----
  const TAU = Math.PI * 2;
  window.__ciMark = (cx, t, K, r, hot) => {
    const c = CI.get(t.id);
    if (!c || !c.story) return;
    const px = 1 / K, cur = COL[c.current] || COL.none;
    cx.save();
    // a merged task's history is settled: its mark recedes so the Done sun's crowd does not outshout the open work, and firms up on hover
    if (c.current === "merged" && !hot) cx.globalAlpha = 0.4;
    if (mark === "ring") {
      // the push ring: one arc per push clockwise from twelve o'clock, each coloured by its outcome; the last is the state now
      const pushes = c.prs.flatMap((q) => q.pushes).slice(-8), n = pushes.length, R = r + 3.2 * px, gap = n > 1 ? Math.min(0.5, 1.4 / n) : 0;
      cx.lineWidth = (hot ? 2 : 1.6) * px;
      pushes.forEach((q, i) => {
        const a0 = -Math.PI / 2 + (TAU * i) / n + gap / 2, a1 = -Math.PI / 2 + (TAU * (i + 1)) / n - gap / 2;
        cx.strokeStyle = COL[i === n - 1 ? c.current === "conflict" ? q.outcome : c.current === "merged" ? "pass" : c.current : q.outcome] || COL.none;
        cx.setLineDash(q.reruns ? [1.2 * px, 1.2 * px] : []);
        cx.beginPath(); cx.arc(t.x, t.y, R, a0, a1); cx.stroke();
      });
      cx.setLineDash([]);
      if (c.conflicting || c.conflicts) {
        // a conflict: a small diamond on the ring at twelve o'clock, solid while it is open, hollow once cleared
        const d = 2 * px, x = t.x, y = t.y - R - 2.2 * px;
        cx.beginPath(); cx.moveTo(x, y - d); cx.lineTo(x + d, y); cx.lineTo(x, y + d); cx.lineTo(x - d, y); cx.closePath();
        if (c.conflicting) { cx.fillStyle = COL.conflict; cx.fill(); } else { cx.strokeStyle = COL.conflict; cx.lineWidth = 0.9 * px; cx.stroke(); }
      }
    } else if (mark === "pip") {
      // the pip: a satellite at one o'clock in the state colour, with the push count beside it once there is more than one
      const x = t.x + (r + 4) * px * 0.9, y = t.y - (r + 4) * px * 0.9;
      cx.fillStyle = "rgba(6,10,20,0.9)"; cx.beginPath(); cx.arc(x, y, 2.9 * px, 0, TAU); cx.fill();
      cx.fillStyle = c.conflicting ? COL.conflict : cur; cx.beginPath(); cx.arc(x, y, 2.1 * px, 0, TAU); cx.fill();
      if (c.pushes > c.prs.length || c.reruns || c.conflicts) {
        cx.font = `500 ${9 * px}px Inter, system-ui, sans-serif`; cx.textBaseline = "middle"; cx.fillStyle = "rgba(219,228,243,0.85)";
        cx.fillText(`${c.pushes}${c.reruns ? "↻" : ""}${c.conflicts ? "⚠" : ""}`, x + 4 * px, y);
      }
    } else {
      // the tag: a pill right of the dot, outlined in the state colour, holding the push count and any re-runs or conflicts
      const label = `${c.pushes}×${c.reruns ? ` ↻${c.reruns}` : ""}${c.conflicts ? ` ⚠${c.conflicts}` : ""}`;
      cx.font = `500 ${9 * px}px Inter, system-ui, sans-serif`;
      const w = cx.measureText(label).width + 7 * px, h = 12 * px, x = t.x + r + 4 * px, y = t.y - h / 2;
      cx.fillStyle = "rgba(6,10,20,0.88)"; cx.strokeStyle = c.conflicting ? COL.conflict : cur; cx.lineWidth = 1 * px;
      cx.beginPath(); cx.roundRect(x, y, w, h, h / 2); cx.fill(); cx.stroke();
      cx.fillStyle = "rgba(219,228,243,0.9)"; cx.textBaseline = "middle"; cx.fillText(label, x + 3.5 * px, t.y + 0.5 * px);
    }
    cx.restore();
  };

  // ---- the Star Map tooltip and task panel ----
  const idIn = (el) => /DEMO-\d+(?!\d)/.exec(el?.textContent || "")?.[0];
  function tipLine(id) {
    const c = CI.get(id);
    if (!c) return "";
    return `<div class="citip">${strip(c.prs.flatMap((p) => p.pushes).slice(-12))}<span class="cw ${c.current}">${word[c.current]}</span><span class="cn">${counts(c)}</span></div>`;
  }
  function panelBlock(id) {
    const c = CI.get(id);
    if (!c) return `<div class="cipanel"><div class="cih"><b>CI</b><span class="k">no pull request yet</span></div></div>`;
    const firstTime = !c.story;
    const rows = c.prs.map((p) => {
      const f = p.pushes.filter((q) => q.outcome === "fail").length, rr = p.pushes.reduce((s, q) => s + q.reruns, 0), rb = p.pushes.filter((q) => q.rebase).length;
      return `<tr><td><a href="${esc(p.url)}">#${p.number}</a></td><td>${strip(p.pushes, "wide")}</td><td><span class="cw ${p.current}">${word[p.current]}</span></td>
        <td class="num">${p.pushes.length}</td><td class="num">${f || "·"}</td><td class="num">${rr || "·"}</td><td class="num">${rb || "·"}</td><td class="num">${p.conflicts.length ? `<span class="cf${p.conflicting ? " now" : ""}">${p.conflicts.length}</span>` : "·"}</td></tr>`;
    }).join("");
    return `<div class="cipanel">
      <div class="cih"><b>CI</b><span class="cw ${c.current}">${word[c.current]}</span>${firstTime ? `<span class="k">· green on its first push</span>` : ""}</div>
      <div class="cinums">
        <div><b>${c.pushes}</b><span>pushes</span></div><div class="${c.fails ? "bad" : ""}"><b>${c.fails}</b><span>failed</span></div>
        <div><b>${c.reruns}</b><span>re-runs</span></div><div><b>${c.rebases}</b><span>rebases</span></div>
        <div class="${c.conflicting ? "cfnow" : ""}"><b>${c.conflicts}</b><span>conflicts</span></div>
      </div>
      <table class="ciprs"><tr class="hd"><td>PR</td><td>pushes, oldest first</td><td>now</td><td title="pushes">●</td><td title="failed">✗</td><td title="re-runs">↻</td><td title="rebases">⤴</td><td title="conflicts">⚠</td></tr>${rows}</table>
      ${c.conflicting ? `<div class="cinote cf">⚠ #${c.head.number} conflicts with main since ${ago(nowS() - c.head.conflicts.at(-1).at)} ago</div>` : ""}
    </div>`;
  }

  // ---- the Kanban card badge and the task modal section ----
  function cardBadge(id) {
    const c = CI.get(id);
    if (!c || !c.story) return null;
    const b = document.createElement("span");
    b.className = `cibadge ${c.current}`;
    b.title = `CI: ${plural(c.pushes, "push")}, ${c.fails} failed, ${plural(c.reruns, "re-run")}, ${plural(c.rebases, "rebase")}, ${plural(c.conflicts, "conflict")}; ${word[c.current]} now`;
    // the state word only when it asks for action; a green or merged task's border and strip say enough
    const act = ["fail", "conflict", "pending"].includes(c.current) ? `<span class="cw ${c.current}">${word[c.current]}</span>` : "";
    b.innerHTML = `${strip(c.prs.flatMap((p) => p.pushes).slice(-6))}${act}${counts(c)}`;
    return b;
  }
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
  function modalSection(id) {
    const c = CI.get(id);
    const s = document.createElement("section");
    s.className = "sec cisec";
    if (!c) { s.innerHTML = `<div class="sh"><span class="t">CI history</span></div><div class="k">No pull request yet.</div>`; return s; }
    s.innerHTML = `<div class="sh"><span class="t">CI history</span><span class="cw ${c.current}">${word[c.current]}</span></div>
      <div class="cinums">
        <div><b>${c.pushes}</b><span>pushes</span></div><div class="${c.fails ? "bad" : ""}"><b>${c.fails}</b><span>failed</span></div>
        <div><b>${c.reruns}</b><span>re-runs</span></div><div><b>${c.rebases}</b><span>rebases</span></div>
        <div class="${c.conflicting ? "cfnow" : ""}"><b>${c.conflicts}</b><span>conflicts</span></div>
      </div>
      ${c.prs.slice().reverse().map((p, k) => `<details class="cipr" ${k === 0 ? "open" : ""}><summary><a href="${esc(p.url)}" onclick="event.stopPropagation()">#${p.number}</a> ${strip(p.pushes, "wide")} <span class="cw ${p.current}">${word[p.current]}</span><span class="k">${plural(p.pushes.length, "push")}${p.conflicts.length ? ` · ${plural(p.conflicts.length, "conflict")}` : ""}</span></summary>
        <div class="tl">${prTimeline(p)}</div></details>`).join("")}
      <div class="k foot">A push is one head commit; its workflows open on click.</div>`;
    // a push row is a toggle: the pointer or Enter/Space opens its workflows
    s.querySelectorAll(".ev.push").forEach((e) => {
      const flip = () => e.setAttribute("aria-expanded", e.classList.toggle("open"));
      Object.assign(e, { tabIndex: 0 }); e.setAttribute("role", "button"); e.setAttribute("aria-expanded", e.classList.contains("open"));
      e.addEventListener("click", flip);
      e.addEventListener("keydown", (k) => { if (k.key === "Enter" || k.key === " ") { k.preventDefault(); flip(); } });
    });
    return s;
  }

  // ---- styles ----
  const css = `
  .cistrip { display: inline-flex; gap: 1.5px; align-items: flex-end; vertical-align: middle; }
  .cistrip i { width: 3px; height: 9px; border-radius: 1px; background: ${COL.none}; }
  .cistrip.wide i { width: 5px; height: 11px; }
  .cistrip i.pass { background: ${COL.pass}; } .cistrip i.fail { background: ${COL.fail}; } .cistrip i.cancelled { background: ${COL.cancelled}; opacity: .55; }
  .cistrip i.pending { background: ${COL.pending}; animation: cipulse 1.4s ease-in-out infinite; }
  .cistrip i.rr { background-image: repeating-linear-gradient(0deg, transparent 0 2px, rgba(6,10,20,.85) 2px 3px); }
  .cistrip i.rb { box-shadow: 0 -2px 0 0 #93c5fd; }
  @keyframes cipulse { 50% { opacity: .35; } }
  .cw { font-size: calc(10.5px * var(--fs)); padding: 0 5px; border-radius: 4px; border: 1px solid currentColor; line-height: 1.5; white-space: nowrap; }
  .cw.pass { color: ${COL.pass}; } .cw.fail { color: ${COL.fail}; } .cw.pending { color: ${COL.pending}; } .cw.merged { color: ${COL.merged}; } .cw.conflict { color: ${COL.conflict}; } .cw.cancelled, .cw.none { color: ${COL.cancelled}; }
  .rr { color: #93c5fd; } .rb { color: #93c5fd; } .cf { color: ${COL.conflict}; } .cf.now { font-weight: 600; }
  #tip .citip { display: flex; gap: 8px; align-items: center; margin-top: 6px; padding-top: 5px; border-top: 1px dashed rgba(148,163,184,.25); font-size: calc(11px * var(--fs)); }
  #tip .citip .cn { display: inline-flex; gap: 6px; color: #94a3b8; }
  .cipanel { margin: 10px 0 6px; padding-top: 8px; border-top: 1px solid rgba(148,163,184,.15); }
  .cih { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; font-size: calc(12px * var(--fs)); }
  .cinums { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 4px; margin: 4px 0 8px; }
  .cinums div { background: rgba(148,163,184,.06); border-radius: 6px; padding: 4px 6px; display: flex; flex-direction: column; min-width: 0; }
  .cinums b { font-size: calc(15px * var(--fs)); font-weight: 500; color: var(--ink); }
  .cinums span { font-size: calc(10px * var(--fs)); color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cinums .bad b { color: ${COL.fail}; } .cinums .cfnow { outline: 1px solid ${COL.conflict}; } .cinums .cfnow b { color: ${COL.conflict}; }
  #panel table.ciprs { width: 100%; font-size: calc(11px * var(--fs)); }
  #panel table.ciprs td { padding: 2px 3px; vertical-align: middle; }
  #panel table.ciprs td.num { text-align: right; font-variant-numeric: tabular-nums; color: #94a3b8; }
  #panel table.ciprs tr.hd td { color: var(--muted); font-size: calc(10px * var(--fs)); }
  .cinote { margin-top: 6px; font-size: calc(11px * var(--fs)); } .cinote.cf { color: ${COL.conflict}; }
  #kb .card .cibadge { display: flex; width: fit-content; max-width: 100%; margin: 4px 0 2px; align-items: center; gap: 4px; font-family: "JetBrains Mono", ui-monospace, monospace; font-size: calc(10px * var(--fs)); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(148,163,184,.2); color: #94a3b8; white-space: nowrap; }
  #kb .card .cibadge.fail { border-color: rgba(251,113,133,.55); } #kb .card .cibadge.conflict { border-color: rgba(251,146,60,.65); } #kb .card .cibadge.pending { border-color: rgba(251,191,36,.5); }
  #kb .card .cibadge .cistrip i { width: 2.5px; height: 8px; } #kb .card .cibadge .cw { font-family: Inter, system-ui, sans-serif; border: 0; padding: 0; }
  #kbm .cisec .sh { display: flex; gap: 8px; align-items: center; }
  #kbm .cisec .cinums { max-width: 460px; }
  #kbm .cipr { border: 1px solid rgba(148,163,184,.13); border-radius: 7px; margin: 6px 0; padding: 4px 8px; }
  #kbm .cipr summary { cursor: pointer; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: calc(12px * var(--fs)); }
  #kbm .cipr summary .k { margin-left: auto; }
  #kbm .tl { margin: 6px 0 2px; border-left: 1px solid rgba(148,163,184,.2); padding-left: 10px; }
  #kbm .ev { display: grid; grid-template-columns: 16px 1fr auto; gap: 6px; align-items: baseline; padding: 3px 0; font-size: calc(11.5px * var(--fs)); }
  #kbm .ev.push { cursor: pointer; } #kbm .ev .wfs { display: none; margin: 3px 0 2px; color: #cbd5e1; } #kbm .ev.open .wfs { display: block; }
  #kbm .ev .ic { text-align: center; color: #94a3b8; } #kbm .ev .ic.rerun, #kbm .ev .ic.rebase { color: #93c5fd; } #kbm .ev .ic.conflict { color: ${COL.conflict}; }
  #kbm .ev.push.fail .ic { color: ${COL.fail}; } #kbm .ev.push.pass .ic { color: ${COL.pass}; } #kbm .ev.push.pending .ic { color: ${COL.pending}; }
  #kbm .ev.open .tx > .cw { } #kbm .ev.push:focus-visible { outline: 1px solid #a78bfa; outline-offset: 1px; border-radius: 4px; } #kbm .ev .ago { color: var(--muted); font-size: calc(10.5px * var(--fs)); }
  #kbm .ev .sha { font-family: "JetBrains Mono", ui-monospace, monospace; font-weight: 400; color: #cbd5e1; }
  #kbm .cisec .foot { margin-top: 4px; font-size: calc(10.5px * var(--fs)); }
  #cimock { position: fixed; z-index: 9; left: 50%; bottom: 14px; transform: translateX(-50%); display: flex; gap: 4px; align-items: center; padding: 4px 6px 4px 10px; border-radius: 9px;
    background: rgba(12,19,34,.94); border: 1px dashed rgba(167,139,250,.6); font: 12px Inter, system-ui, sans-serif; color: #cbd5e1; }
  #cimock button { font: inherit; color: inherit; background: transparent; border: 1px solid rgba(148,163,184,.25); border-radius: 6px; padding: 2px 9px; cursor: pointer; }
  #cimock button.on { background: rgba(167,139,250,.25); border-color: #a78bfa; color: #fff; }
  #cimock select { font: inherit; color: inherit; background: rgba(15,23,42,.9); border: 1px solid rgba(148,163,184,.25); border-radius: 6px; padding: 2px 4px; margin-right: 6px; }
  #cimock .lg { margin-left: 8px; color: #94a3b8; font-size: 11px; }
  `;

  // ---- wiring: observe the page and add the CI pieces wherever it draws a task ----
  function decorate() {
    const tip = document.getElementById("tip");
    if (tip && !tip.querySelector(".citip")) { const id = idIn(tip.querySelector(".n") || tip); if (id && CI.has(id)) tip.insertAdjacentHTML("beforeend", tipLine(id)); }
    const panel = document.getElementById("panel");
    if (panel && panel.querySelector("h2") && !panel.querySelector(".cipanel")) {
      const id = idIn(panel.querySelector("h2"));
      const table = panel.querySelector(":scope > table");
      // a Board task's panel only; a machine task's reads "task · <flow> · <state>"
      if (id && table && (panel.querySelector(".k")?.textContent || "").startsWith("task · click")) table.insertAdjacentHTML("afterend", panelBlock(id));
    }
    for (const card of document.querySelectorAll("#kb .card[data-id]")) {
      const top = card.querySelector(".top");
      if (!top || card.querySelector(".cibadge, .cinone")) continue;
      // its own row under the title: the top row already holds the id, the PR chip and the run button at the narrowest column
      const b = cardBadge(card.dataset.id), t = card.querySelector(".t");
      if (b && t) t.after(b);
      else top.append(Object.assign(document.createElement("i"), { className: "cinone", hidden: true }));
    }
    const modal = document.querySelector("#kbm .modal.tv");
    if (modal && !modal.querySelector(".cisec")) {
      const id = idIn(modal.querySelector(".tvhead .k"));
      const desc = [...modal.querySelectorAll(".tvbody > section.sec")][0];
      if (id && desc) desc.before(modalSection(id));
    }
  }

  function control() {
    if (document.getElementById("cimock")) return;
    const bar = document.createElement("div");
    bar.id = "cimock";
    // the state picker reloads into a preset, for viewers that cannot edit the address (an embedded copy)
    const pick = `<select aria-label="Mockup state"><option value="">state…</option>${Object.keys(STATES).map((k) => `<option value="${k}">${k}</option>`).join("")}</select>`;
    bar.innerHTML = `<span>mockup</span>${pick}<span>dot mark</span>${MARKS.map((m) => `<button data-m="${m}" class="${m === mark ? "on" : ""}">${m}</button>`).join("")}<span class="lg">● push · ↻ re-run · ⤴ rebase · ⚠ conflict</span>`;
    bar.querySelector("select").addEventListener("change", (e) => { if (e.target.value) location.search = `?s=${e.target.value}&mark=${mark}`; });
    bar.addEventListener("click", (e) => {
      const m = e.target.closest("button")?.dataset.m;
      if (!m) return;
      mark = m;
      bar.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.m === m));
      const p = new URLSearchParams(location.search); p.set("mark", m); window.history.replaceState(null, "", "?" + p);
      window.dispatchEvent(new Event("resize")); // the canvas draws only on a change; a resize repaints it
    });
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
        if (idIn(document.querySelector("#panel.open h2")) === id) return void (PICK[key] = id);
        if (tries > 0) openPanel(key, order.length > 1 && idIn(document.querySelector("#panel.open h2")) ? order.slice(1) : order, tries - 1);
      }, 300);
    }, 100);
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
    if (preset?.modal) {
      const open = (tries = 60) => {
        const card = document.querySelector(`#kb .card[data-id="${PICK[preset.modal]}"]`);
        if (!card) return tries > 0 && setTimeout(() => open(tries - 1), 150);
        card.scrollIntoView({ block: "center" }); card.click();
      };
      setTimeout(open, 600);
    }
  });
})();
