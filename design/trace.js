// ---- back-trace: hovering a task or session lights the path it took through this level's machine, in order ----
// A Board task's whole life comes from its lane history (the build fetches /api/history?task=ID on hover; the mockup bakes the real
// backlog_task_events rows of the snapshot's tasks into history.js). A session's comes from its replayed trail (the build fetches
// /api/history?session=SID; the mockup uses the trail the snapshot carries). Each hop lights the routed path it took, numbered in order, a
// path taken twice carrying both numbers; a hop the machine has no path for is drawn straight and dashed in red. Each visited state carries
// the time spent in it (summed over visits, with the visit count), the rest of the scene dims, and DAGs draw no tethers. On the Board, the
// skill-machine moons the task has sessions in are ringed with their session count. Hover traces; a click pins the trace and opens the
// panel with every step.
const LEGACY = { Blocked: "Waiting" };
const laneId = (n) => board.machine.states.find((s) => s.name.toLowerCase() === (LEGACY[n] || n).toLowerCase())?.id;
const TRACE = "#fbbf24", OFF = "#fb7185";
let pinned = null;
const fmtDur = (s) => { s = Math.max(0, s); const m = Math.round(s / 60), h = Math.floor(m / 60), d = Math.floor(h / 24);
  return d >= 2 ? `${d}d ${h % 24}h` : h ? `${h}h ${m % 60}m` : s >= 60 ? `${m}m` : `${Math.round(s)}s`; };
const fmtAt = (t) => new Date(t * 1000).toLocaleString("en-US", { timeZone: TZ, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
// one run: its hops in order (self-steps count as steps but draw no hop), the time in each state, loops (a hop back into a state the run has
// already been in) and the elapsed time from its first step to now, or to the final state it ended in
function runOf(h) {
  let steps, now, finals;
  if (h.kind === "task") {
    const rows = (window.HIST[h.o.id] || []).filter((r) => r[0] <= S.now);
    steps = rows.map(([at, a, b]) => ({ at, from: a == null ? "new" : laneId(a), to: laneId(b) })).filter((s) => s.from !== s.to);
    now = S.now; finals = new Set(board.machine.states.filter((s) => s.final).map((s) => s.id));
  } else {
    const fl = S.flows[h.o.flow], init = fl.machine.states.find((s) => s.initial)?.id, tr = h.o.trail.filter((t) => t.at <= T);
    steps = tr.map((t, i) => ({ at: t.at, from: i ? tr[i - 1].state : init, to: t.state, event: t.event }));
    now = T; finals = new Set(fl.machine.states.filter((s) => s.final).map((s) => s.id));
  }
  const hops = steps.filter((s) => s.from !== s.to), stay = {}, visits = {}, seen = new Set(hops.length ? [hops[0].from] : []);
  let loops = 0, end = now;
  hops.forEach((s, i) => { if (seen.has(s.to)) loops++; seen.add(s.to); s.n = i + 1;
    const until = hops[i + 1]?.at ?? (finals.has(s.to) ? s.at : now); s.stay = until - s.at;
    stay[s.to] = (stay[s.to] || 0) + s.stay; visits[s.to] = (visits[s.to] || 0) + 1; if (!hops[i + 1] && finals.has(s.to)) end = s.at; });
  return { steps, hops, stay, visits, loops, start: steps[0]?.at ?? now, end, total: h.kind === "session" ? h.o.steps : steps.length };
}
// mockup only: ?trace=TASK-ID pins that task's trace (on a machine level, its session's) so a screenshot need not catch a moving dot
const PIN = new URLSearchParams(location.search).get("trace");
const pinOf = () => { if (!PIN) return null; const t = scene.tasks.find((q) => q.id === PIN && !q.gone); if (t) return { kind: "task", o: t };
  const s = scene.sessions.find((q) => q.task === PIN && q._x !== undefined); return s ? { kind: "session", o: s } : null; };
const traced = () => (hover && (hover.kind === "task" || hover.kind === "session") ? hover : pinned || pinOf());
// mockup only: &card shows the pinned body's hover card beside it; &panel opens its pinned panel, as a click would
const Q = new URLSearchParams(location.search);
// mockup only: &level=STATE/MACHINE opens that level (this script runs before the page reads its saved path)
if (Q.has("level")) { const [id, flow] = Q.get("level").split("/");
  try { localStorage.setItem("fv.path", JSON.stringify([{ kind: "board" }, ...(id ? [{ kind: "state", id }] : []), ...(flow ? [{ kind: "machine", flow }] : [])])); } catch {} }
setInterval(() => { const p = !hover && Q.has("card") && pinOf(); if (!p) return; const bx = p.kind === "task" ? p.o.x : p.o._x, by = p.kind === "task" ? p.o.y : p.o._y;
  tip.innerHTML = traceCard(p); tip.style.left = `${bx * view.k + view.x + 22}px`; tip.style.top = `${by * view.k + view.y + 18}px`; tip.style.opacity = 1; }, 100);
if (Q.has("panel")) setTimeout(() => { const p = pinOf(); if (p) { hover = p; click(0, 0); hover = null; } }, 600);
function badge(p, nums, col) {
  const s = nums.join(" · "), sz = 10.5 / K, w = Math.max(16 / K, textW(s, 10.5) / K + 10 / K), h = 16 / K;
  cx.fillStyle = "rgba(6,10,20,0.96)"; cx.strokeStyle = rgba(col, 0.95); cx.lineWidth = 1.2 / K; cx.beginPath(); cx.roundRect(p.x - w / 2, p.y - h / 2, w, h, h / 2); cx.fill(); cx.stroke();
  text(s, p.x, p.y + 0.5 / K, sz, "#fef3c7", "center", 600);
}
function pill(s, x, y, col) { const sz = 10.5 / K, w = textW(s, 10.5) / K + 12 / K, h = 17 / K;
  cx.fillStyle = "rgba(6,10,20,0.92)"; cx.strokeStyle = rgba(col, 0.6); cx.lineWidth = 1 / K; cx.beginPath(); cx.roundRect(x - w / 2, y - h / 2, w, h, 4 / K); cx.fill(); cx.stroke();
  text(s, x, y + 0.5 / K, sz, "#f8fafc", "center", 500); }
function drawTrace(k, x, y) {
  const h = traced(); if (!h) return;
  const run = runOf(h), dpr = devicePixelRatio || 1;
  const onBoard = h.kind === "task" && scene.bEdges.length, onMachine = h.kind === "session" && scene.mEdges.length;
  if (!onBoard && !onMachine) return drawTraceBody(h);
  // a hover only lights the path; a click-pinned trace is the focused setting, so everything else steps back under a dark veil
  if (pinned && h.o === pinned.o) { cx.setTransform(dpr, 0, 0, dpr, 0, 0); cx.fillStyle = "rgba(4,6,11,0.66)"; cx.fillRect(0, 0, W, H); cx.setTransform(k * dpr, 0, 0, k * dpr, x * dpr, y * dpr); }
  const states = onBoard ? scene.galaxies : scene.mStates, rOf = (s) => (onBoard ? s.r : stateR(s));
  const byPath = new Map();
  for (const s of run.hops) { const a = states[s.from], b = states[s.to]; if (!a || !b) continue;
    let e = onBoard ? scene.bEdges.find((q) => !q.loop && q.source === s.from && q.target === s.to) : scene.mEdges.find((q) => q.source === s.from && q.target === s.to);
    // a hop with no path bows well off the straight line, so it reads as its own stroke rather than lying across the routed paths
    const off = !e; e = off ? { p0: a, c: { x: (a.x + b.x) / 2 - (b.y - a.y) * 0.28, y: (a.y + b.y) / 2 + (b.x - a.x) * 0.28 }, p1: b } : onBoard ? e : curveOf(e.a, e.b);
    const key = `${s.from}>${s.to}`; if (!byPath.has(key)) byPath.set(key, { e, off, a, b, nums: [] }); byPath.get(key).nums.push(s.n); }
  for (const { e, off, a, b } of byPath.values()) {
    const L = Math.hypot(e.p1.x - e.p0.x, e.p1.y - e.p0.y) || 1, t0 = onBoard && !off ? 0 : Math.min(0.4, (rOf(a) + 2) / L), t1 = onBoard && !off ? 1 : 1 - Math.min(0.4, (rOf(b) + 4) / L);
    const g = cx.createLinearGradient(a.x, a.y, b.x, b.y); g.addColorStop(0, rgba(off ? OFF : a.color, 0.95)); g.addColorStop(1, rgba(off ? OFF : b.color, 0.95));
    cx.strokeStyle = g; cx.lineWidth = 2.6 / Math.max(1, ZS); cx.setLineDash(off ? [5 / K, 5 / K] : []);
    cx.beginPath(); for (let i = 0; i <= 24; i++) { const p = bez(e.p0, e.c, e.p1, t0 + ((t1 - t0) * i) / 24); i ? cx.lineTo(p.x, p.y) : cx.moveTo(p.x, p.y); } cx.stroke(); cx.setLineDash([]);
    arrow(bez(e.p0, e.c, e.p1, t1 - 0.02), bez(e.p0, e.c, e.p1, t1), rgba(off ? OFF : b.color, 0.95), 9);
  }
  // each visited state: its rim and name firm up, with the time it held the task beside it (summed, with the visit count when it came back)
  const taken = [], box = (x, y, w, h) => ({ x0: x - w / 2, x1: x + w / 2, y0: y - h / 2, y1: y + h / 2 });
  const clash = (b) => taken.some((o) => b.x0 < o.x1 + 4 / K && b.x1 > o.x0 - 4 / K && b.y0 < o.y1 + 4 / K && b.y1 > o.y0 - 4 / K);
  for (const s of Object.values(states)) if (s.lab) taken.push(box(s.lab.x, s.lab.y, textW(s.name, 13) / K, 18 / K));
  for (const [id, secs] of Object.entries(run.stay)) { const s = states[id]; if (!s) continue; const r = rOf(s), n = run.visits[id], t = `${fmtDur(secs)}${n > 1 ? ` · ${n}×` : ""}`;
    circle(s.x, s.y, r, rgba(s.color, 1), 2.2 / Math.max(1, ZS));
    // the time sits on the side away from the state's name, or the other side if that is taken
    const pw = textW(t, 10.5) / K + 12 / K, ph = 17 / K, R = onBoard ? s.R : r + 12 / K, sides = s.lab.y < s.y ? [1, -1] : [-1, 1];
    const py = sides.map((d) => s.y + d * (R + 16 / K)).find((y) => !clash(box(s.x, y, pw, ph))) ?? s.y + sides[0] * (R + 16 / K);
    label(s.name, s.lab.x, s.lab.y, true, null, onBoard ? 13 : 12.5); pill(t, s.x, py, s.color); taken.push(box(s.x, py, pw, ph)); }
  // a path's step numbers sit at its middle, or slide along it to the nearest spot clear of other numbers, times and state names
  for (const { e, off, nums } of byPath.values()) { const s = nums.join(" · "), w = Math.max(16, textW(s, 10.5) + 10) / K, h = 16 / K;
    const p = [0.5, 0.4, 0.6, 0.32, 0.68, 0.25, 0.75, 0.18, 0.82].map((t) => bez(e.p0, e.c, e.p1, t)).find((q) => !clash(box(q.x, q.y, w, h))) || bez(e.p0, e.c, e.p1, 0.5);
    taken.push(box(p.x, p.y, w, h)); badge(p, nums, off ? OFF : TRACE); }
  const first = states[run.hops[0]?.from]; if (first && !run.stay[first.id]) { circle(first.x, first.y, rOf(first), rgba(first.color, 0.9), 1.6 / Math.max(1, ZS)); if (onBoard) label(first.name, first.lab.x, first.lab.y, true, null, 13); }
  // on the Board, the lifecycle machines the task has sessions in: their moon is ringed with the session count, a sub-state it holds too
  if (onBoard) { const ses = Object.values(S.flows).filter((f) => f.name !== "board").flatMap((f) => f.agents.filter((s) => s.task === h.o.id).map((s) => ({ flow: f.name, state: s.state })));
    const per = {}; for (const s of ses) per[s.flow] = (per[s.flow] || 0) + 1;
    for (const m of scene.moons) { const n = per[m.name]; if (!n) continue; circle(m.x, m.y, m.r + 6, rgba(TRACE, 0.95), 1.6 / Math.max(1, ZS));
      text(`${n} session${n === 1 ? "" : "s"}`, m.x, m.y - m.r - 14 / K, 9.5 / K, TRACE, "center", 600); }
    for (const t of scene.sats) if (ses.some((s) => s.flow === t.machine && s.state === t.state)) circle(t.x, t.y, t.r + 5, rgba(TRACE, 0.95), 1.4 / Math.max(1, ZS)); }
  drawTraceBody(h);
}
// the traced task or session itself, ringed, on top of everything
function drawTraceBody(h) { const o = h.o, px = h.kind === "task" ? o.x : o._x, py = h.kind === "task" ? o.y : o._y; if (px === undefined) return;
  circle(px, py, 9 / K, rgba(TRACE, 0.9), 1.6 / K); dot(px, py, 4.5 / K, rgba(modelColor(o.model), 1)); }
// the hover card: what it is, then the run in numbers; the forecast line is Proposal D's slot, shown with an example value until it is built
function traceCard(h) {
  const r = runOf(h), o = h.o, live = r.end === (h.kind === "task" ? S.now : T);
  const head = h.kind === "task" ? `<div class="k">task · ${esc(stateName(o.state))} · click to pin its path</div><div class="n">${esc(o.id)}</div>${esc(o.title)}`
    : `<div class="k">${esc(o.kind)} session · ${esc(o.flow)} · click to pin its path</div><div class="n">${esc(o.task || o.title)}</div>`;
  return `${head}<div class="stats"><span><b>${r.total}</b> step${r.total === 1 ? "" : "s"}</span><span><b>${r.loops}</b> loop${r.loops === 1 ? "" : "s"}</span><span><b>${fmtDur(r.end - r.start)}</b> ${live ? "so far" : "start to end"}</span></div>
    <div class="k">since ${fmtAt(r.start)} MST${h.kind === "session" && o.steps > o.trail.length ? ` · showing the last ${o.trail.length}` : ""}</div>
    ${live ? `<div class="fc">forecast · <i>Proposal D, not built</i> · e.g. 71% reach ${h.kind === "task" ? "Done" : "pr_opened"}, ~1d 6h left</div>` : ""}`;
}
// the pinned panel's step table: every hop with when it happened and how long the run stayed where it landed
function traceTable(h) { const r = runOf(h);
  return `<div class="k" style="margin-top:12px">path · ${r.total} steps · ${r.loops} loops · ${fmtDur(r.end - r.start)}</div><table class="trace">
    ${r.hops.map((s) => `<tr><td>${s.n}</td><td>${fmtAt(s.at)}</td><td>${esc(h.kind === "task" ? stateName(s.from) : s.from)} → ${esc(h.kind === "task" ? stateName(s.to) : s.to)}</td><td>${fmtDur(s.stay)}</td></tr>`).join("")}</table>`; }
