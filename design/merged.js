// Design round (doc-111 D9): what happens between Review and Done. The fold on the Board's Review → Done path opens this level, redrawn
// here as three candidate views of one causal sequence: a PR merges to main, main-follow (on push) writes MERGED and the task moves to
// Done, and the merge cues apply-on-merge and graph-refresh. ?merged=a|b|c picks the view (Junction, Orrery, Ledger), ?ms=live|fail|cross
// the scenario and ?ts=125|150 the browser text size. Merges, runs and timings are simulated from the snapshot's tasks and DAG steps, with
// volume (about ten an hour in working hours) and run durations shaped like a day of live apply-on-merge, graph-refresh and main-follow runs.
"use strict";
{
const P = new URLSearchParams(location.search);
const VARS = { a: "Junction", b: "Orrery", c: "Ledger" };
const SCNS = {
  live: "A normal day: a merge every ~25 s. Three hours ago apply-on-merge failed seven times in a row at apply_deploy; a forced rerun cleared it.",
  fail: "apply-on-merge keeps failing at apply_deploy. A later merge applies only its own diff, so each failure stays pinned until a forced rerun.",
  cross: "A skills merge: nothing applies here, the 5-minute main-follow pass writes MERGED, and its pin bump merge applies it later.",
};
const VAR = VARS[P.get("merged")] ? P.get("merged") : "c", SCN = SCNS[P.get("ms")] ? P.get("ms") : "live";
if (+P.get("ts")) document.documentElement.style.fontSize = `${+P.get("ts")}%`;
const rootFs = () => parseFloat(getComputedStyle(document.documentElement).fontSize) / 16;
let F = rootFs(); // browser text size: canvas type and the room it takes scale with it
const NM = { mf: "main-follow", aom: "apply-on-merge", gr: "graph-refresh" }, KS = ["mf", "aom", "gr"];
const mine = (l = level()) => l?.kind === "fold" && l.path?.[0] === "review" && l.path?.[1] === "done";
const SKIP = "#3b4760", RED = DAG_COLOR.failed, CROSS = "#c4b5fd";
const SCOL = (st) => (st === "skipped" ? SKIP : st === "waiting" ? CROSS : DAG_COLOR[st] || "#94a3b8");

// ---- simulated merges ----
let sd = 20261006; const rn = () => ((sd = (sd * 16807) % 2147483647) / 2147483647);
const hex = (n) => Array.from({ length: n }, () => "0123456789abcdef"[Math.floor(rn() * 16)]).join("");
// [apply-on-merge start, main-follow start, graph-refresh start, their three durations], seconds after the merge, from a day of live runs
const TU = [[2,78,54,37,11,23],[21,2,43,8,11,24],[2,33,23,6,12,9],[18,2,42,7,15,22],[20,2,42,7,11,22],[2,92,54,37,18,10],[2,31,31,8,41,54],[14,2,36,7,24,64],[36,2,59,6,24,27],[2,26,32,8,16,32],[2,177,58,41,13,33],[12,2,50,9,14,12],[34,2,55,8,21,87],[2,88,28,11,18,31],[2,116,42,12,19,41],[31,2,52,11,13,24],[18,2,70,39,14,26],[2,52,46,18,14,33],[17,2,114,12,48,17],[25,2,68,8,15,129],[46,2,114,50,24,25],[27,2,51,11,15,35],[14,2,40,10,14,49],[30,2,83,15,17,12],[15,2,41,8,33,35],[2,75,25,8,12,29],[2,24,42,9,32,37],[26,2,52,8,36,36],[2,8,71,15,28,10],[2,53,29,11,25,144],[17,2,73,43,15,32]];
const HOURLY = { 9: 1, 10: 10, 11: 10, 12: 12, 13: 10, 14: 9, 15: 5, 16: 11, 17: 6, 18: 9, 19: 6, 21: 9, 22: 2 }; // merges per MST hour
const HOUR = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", hourCycle: "h23" }), mstHour = (t) => +HOUR.format(new Date(t * 1000)) % 24;
const hms = (t) => new Date(t * 1000).toLocaleTimeString("en-GB", { timeZone: TZ, hour12: false });
const dur = (s) => { s = Math.max(0, Math.round(s)); return s < 60 ? `${s} s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

const DEPTH = {}, NL = {}, STEPS = {};
for (const k of KS) { const steps = dagBy[NM[k]].steps, by = Object.fromEntries(steps.map((s) => [s.name, s])), d = {};
  const dep = (n) => (d[n] ??= 1 + Math.max(-1, ...by[n].depends.filter((x) => by[x] && x !== n).map(dep)));
  steps.forEach((s) => dep(s.name)); DEPTH[k] = d; NL[k] = Math.max(0, ...Object.values(d)) + 1; STEPS[k] = steps.map((s) => s.name); }
const CHAIN = ["apply_migrations", "apply_images", "apply_deploy", "apply_systemd", "push_dashboards"].filter((n) => STEPS.aom.includes(n));
const BRANCH = STEPS.aom.filter((n) => DEPTH.aom[n] === 2 && !CHAIN.includes(n)), ALWAYS = STEPS.aom.filter((n) => !CHAIN.includes(n) && !BRANCH.includes(n));
const FAILS = CHAIN.includes("apply_deploy") ? "apply_deploy" : CHAIN.at(-1);
const PIN = { skills: BRANCH.filter((n) => n.startsWith("apply_skills")), "backlog.md": BRANCH.filter((n) => n === "apply_board"), starpulse: BRANCH.filter((n) => n === "apply_flow_view") };
// classify picks what a merge applies from the paths it changed; the deploy chain runs as one
function pickApplied(chain) { const s = new Set(ALWAYS); if (chain || rn() < 0.3) CHAIN.forEach((n) => s.add(n));
  BRANCH.forEach((n) => rn() < 0.22 && s.add(n)); if (s.size === ALWAYS.length) s.add(BRANCH[Math.floor(rn() * BRANCH.length)]); return s; }
const shortApplied = (r) => [...(CHAIN.some((n) => r.applied.has(n)) ? ["deploy chain"] : []), ...BRANCH.filter((n) => r.applied.has(n)).map((n) => n.replace(/^apply_/, "").replace(/_/g, " "))].join(", ");

// a run's steps take equal slices of its duration by depth; steps classify did not pick are skipped when it finishes; a failed step
// leaves the rest of its chain unrun and fails verify_applied
function stepSt(r, name, t) {
  if (!r) return "not_started";
  const L = NL[r.k], d = DEPTH[r.k][name], s = r.start + (r.dur * d) / L, e = r.start + (r.dur * (d + 1)) / L, clsEnd = r.start + (r.dur * 2) / L;
  if (r.k === "aom" && !r.applied.has(name)) return t >= clsEnd ? "skipped" : "not_started";
  if (r.k === "aom" && r.fail) { const fd = DEPTH.aom[r.fail];
    if (CHAIN.includes(name) && d > fd) return t >= r.start + (r.dur * (fd + 1)) / L ? "skipped" : "not_started";
    if (name === r.fail || name === "verify_applied") return t < s ? "not_started" : t < e ? "running" : "failed"; }
  return t < s ? "not_started" : t < e ? "running" : "succeeded";
}
const runSt = (r, t) => (!r ? null : t < r.start ? "queued" : t < r.end ? "running" : r.fail ? "failed" : "succeeded");
const curStep = (r, t) => STEPS[r.k].find((n) => stepSt(r, n, t) === "running");

const NOW0 = SCN === "cross" ? Math.ceil((S.now + 50) / 300) * 300 - 50 : S.now, P0 = performance.now(); // cross: the 5-minute pass lands ~45 s after its merge
const now = () => NOW0 + (performance.now() - P0) / 1000;
const tasksIn = (st) => board.agents.filter((a) => a.state === st);
const DONE = tasksIn("done"), FEED = [...tasksIn("in_progress"), ...tasksIn("ready")];
const prOf = (t) => { const m = (t?.prs?.at(-1) || "").match(/github\.com\/[^/]+\/([^/]+)\/pull\/(\d+)/); return m ? { repo: m[1], n: +m[2] } : null; };
const merges = [], RERUNS = []; let prSeq = 1830, tuI = 0;
function addMerge(o) {
  const m = { t: o.t, task: o.task || null, title: o.title || o.task?.title || "", repo: o.repo || "trantor", pr: o.pr || prSeq--, sha: hex(7), cross: !!o.cross, bumpOf: o.bumpOf || null, bump: null };
  const tu = TU[tuI++ % TU.length];
  if (m.cross) { const s = Math.ceil((m.t + 4) / 300) * 300 + 2; m.runs = { mf: { k: "mf", start: s, dur: 11 + Math.round(rn() * 6) } }; }
  else m.runs = { mf: { k: "mf", start: m.t + tu[1], dur: tu[4] }, aom: { k: "aom", start: m.t + tu[0], dur: tu[3], applied: o.applied || pickApplied(!!o.fail), fail: o.fail || null }, gr: { k: "gr", start: m.t + tu[2], dur: tu[5] } };
  for (const r of Object.values(m.runs)) r.end = r.start + r.dur;
  m.mergedAt = m.runs.mf.end; m.ref = { kind: "mgMerge", o: m };
  merges.push(m); merges.sort((a, b) => b.t - a.t); return m;
}
{ const times = [];
  for (let h = Math.floor((NOW0 - 86400) / 3600) * 3600; h < NOW0; h += 3600) for (let i = 0, n = HOURLY[mstHour(h)] || 0; i < n; i++) { const t = Math.round(h + rn() * 3600); if (t > NOW0 - 86400 && t < NOW0 - 150) times.push(t); }
  times.sort((a, b) => b - a);
  const anyCross = DONE.some((t) => prOf(t) && prOf(t).repo !== "trantor"), streak = times.findIndex((t) => NOW0 - t > 3 * 3600);
  times.forEach((t, i) => { const task = DONE[i % DONE.length], pr = i < DONE.length ? prOf(task) : null;
    const cross = anyCross ? (pr && pr.repo !== "trantor" ? pr.repo : null) : i === 4 ? "backlog.md" : i === 13 ? "skills" : null;
    const fail = cross ? null : SCN === "fail" ? (i < 3 ? FAILS : null) : SCN === "live" && i >= streak && i < streak + 7 ? FAILS : null;
    addMerge({ t, task, cross, repo: cross || "trantor", pr: cross ? pr?.n || 20 + Math.floor(rn() * 40) : pr?.n, fail }); });
  if (SCN === "live" && streak >= 0) RERUNS.push({ start: times[streak] + 240, dur: 52, upto: times[streak] });
  for (const m of merges.filter((x) => x.cross)) { const bt = m.mergedAt + 600 + rn() * 900; if (bt < NOW0 - 150) m.bump = addMerge({ t: Math.round(bt), title: `bump the ${m.repo} pin`, applied: new Set([...ALWAYS, ...(PIN[m.repo] || [])]), bumpOf: m }); } }
for (const r of RERUNS) { r.end = r.start + r.dur; r.ref = { kind: "mgRerun", o: r }; }
// a failed apply stays unapplied until a later run applies the same step or a forced rerun reapplies everything since
function resolver(m, t) {
  const r = m.runs.aom; if (!r?.fail) return null;
  const rr = RERUNS.find((x) => x.end <= t && x.upto >= m.t && x.start >= r.end - 1); if (rr) return { at: rr.end, by: "a forced rerun" };
  const x = merges.filter((y) => y.t > m.t && y.runs.aom && !y.runs.aom.fail && y.runs.aom.applied.has(r.fail) && y.runs.aom.end <= t).at(-1);
  return x ? { at: x.runs.aom.end, by: `merge ${x.sha}, which applied ${r.fail}` } : null;
}
const pinnedAt = (t) => merges.filter((m) => m.runs.aom?.fail && m.runs.aom.end <= t && !resolver(m, t));
const worst = (m, t) => { const s = Object.values(m.runs).map((r) => runSt(r, t)); return s.includes("failed") ? "failed" : s.includes("running") ? "running" : s.includes("queued") ? "queued" : m.cross && !m.bump ? "waiting" : "succeeded"; };

// ---- live: the Review queue merges one task about every 25 s; each waits in Review until main-follow writes MERGED ----
let queue = tasksIn("review").map((t) => ({ t })), feedAt = 0, nextAt = now() + 6, crossSent = false, deployBroken = SCN === "fail";
queue.forEach((q) => (q.ref = { kind: "mgQ", o: q }));
function refill() { while (queue.filter((q) => !q.merged).length < 3 && FEED.length) { const q = { t: FEED[feedAt++ % FEED.length], enter: clock }; q.ref = { kind: "mgQ", o: q }; queue.push(q); } }
function arrive(kind) {
  refill(); const q = queue.find((x) => !x.merged), cross = kind === "cross" ? "skills" : null, t = now();
  const m = addMerge({ t, task: q.t, cross, repo: cross || "trantor", pr: cross ? 40 + Math.floor(rn() * 20) : undefined, fail: !cross && deployBroken ? FAILS : null });
  q.merged = m; m.fresh = clock; if (cross) m.wantBump = m.mergedAt + 20; refill(); fx("J");
}
const PUL = [], COM = [], SEEN = new Map(); let HITS = [], sel = null, lastClock = 0;
function fx(where, delay = 0, col = ACT) { const p = scene.mg?.[where]; if (p) PUL.push({ x: p.x, y: p.y, r: p.r || 6, t0: clock + delay, col, grow: 30 }); }
function tick() {
  const t = now(); if (t >= nextAt) { arrive(SCN === "cross" && !crossSent ? ((crossSent = true), "cross") : null); nextAt = t + 25; }
  for (const m of merges) if (m.wantBump && t >= m.wantBump) { m.bump = addMerge({ t, title: `bump the ${m.repo} pin`, applied: new Set([...ALWAYS, ...(PIN[m.repo] || [])]), bumpOf: m }); m.bump.fresh = clock; m.wantBump = null; fx("J"); }
  for (const q of queue) if (q.merged && !q.gone && t >= q.merged.mergedAt) { q.gone = clock; const L = scene.mg; if (!L) continue;
    const a = { x: L.rv.x, y: L.rv.y }, b = { x: L.dn.x, y: L.dn.y }; COM.push({ p0: a, c: { x: (a.x + b.x) / 2, y: a.y }, p1: b, t0: clock, dur: 1.6, col: modelColor(q.t.model) });
    fx("mg", 0.7); fx("dn", 1.6, BOARD_COLOR.done); }
  queue = queue.filter((q) => !q.gone || clock - q.gone < 1.6);
  for (const m of merges) { m._a = Math.min(1, (m._a ?? (m.fresh ? 0 : 1)) + (clock - lastClock) * 2); }
}
const runningAny = (k) => merges.some((m) => m.t > now() - 900 && runSt(m.runs[k], now()) === "running") || (k === "aom" && RERUNS.some((r) => now() >= r.start && now() < r.end));
const focusM = () => (hover?.kind === "mgMerge" ? hover.o : panelSel() || merges.find((m) => !m.cross && m.t <= now()));
const panelSel = () => (panel.classList.contains("open") && panel.classList.contains("mg") ? sel : null);
const refs = new Map(), ref = (kind, key, o) => (refs.get(`${kind}:${key}`) || refs.set(`${kind}:${key}`, { kind, o }).get(`${kind}:${key}`));
const STAR = Object.fromEntries(KS.map((k) => [k, star(NM[k], 0, 0)])), GL = Object.fromEntries(KS.map((k) => [k, glyph(dagBy[NM[k]])]));

// ---- drawing ----
const T_ = (s, x, y, size, col, align = "left", w = 400) => text(s, x, y, (size * F) / K, col, align, w);
function clip(s, max, size, w = 400) { cx.font = `${w} ${(size * F) / K}px Inter, system-ui, sans-serif`; if (cx.measureText(s).width <= max) return s;
  let lo = 0, hi = s.length; while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (cx.measureText(s.slice(0, mid) + "…").width <= max) lo = mid; else hi = mid - 1; } return s.slice(0, lo) + "…"; }
const MUTED = (a = 0.6) => rgba("#94a3b8", a), INK = (a = 0.92) => rgba("#dbe4f3", a);
function star4(x, y, r, col) { r /= K ** 0.5; cx.fillStyle = col; cx.beginPath(); for (let i = 0; i < 8; i++) { const a = -Math.PI / 2 + (i * Math.PI) / 4, rr = i % 2 ? r * 0.38 : r; cx.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr); } cx.closePath(); cx.fill(); }
function line(pts, col, w = 1, dash) { cx.strokeStyle = col; cx.lineWidth = w / K ** 0.5; cx.setLineDash((dash || []).map((d) => d / K)); cx.beginPath(); pts.forEach((p, i) => (i ? cx.lineTo(p.x, p.y) : cx.moveTo(p.x, p.y))); cx.stroke(); cx.setLineDash([]); }
// a rail: the dashed stream the page draws for every action, brighter and moving while its DAG runs; a cue's dots are sparser
function rail(pts, a, b, hot, cue) { const heat = hot ? 1 : 0; flow({ ...pts[0], color: a }, { ...pts.at(-1), color: b }, (cue ? 0.32 : 0.45) + heat * 0.45, heat, cue ? [1.5, 7] : [2, 5]);
  cx.beginPath(); pts.forEach((p, i) => (i ? (p.c ? cx.quadraticCurveTo(p.c.x, p.c.y, p.x, p.y) : cx.lineTo(p.x, p.y)) : cx.moveTo(p.x, p.y))); cx.stroke(); cx.setLineDash([]); }
// a DAG's own step graph, as the Board draws it: links streaming toward the step that waits, ringed steps in their status colour
function drawGlyph(k, x, y, sc, st, o = {}) {
  const g = GL[k], nr = (g.nodes.length === 1 ? 5 : 4) * Math.sqrt(sc) * (o.hot ? 1.12 : 1), a = o.alpha ?? 1;
  for (const [p, q] of g.links) { const A = { x: x + p.x * sc, y: y + p.y * sc }, B = { x: x + q.x * sc, y: y + q.y * sc }, sp = st(p.name), sq = st(q.name), dx = (B.x - A.x) / 2;
    if (o.mini) { cx.strokeStyle = rgba(SCOL(sq === "not_started" || sq === "skipped" ? sq : sp), 0.4 * a); cx.lineWidth = 0.8 / K ** 0.5; }
    else flow({ ...A, color: SCOL(sp) }, { ...B, color: SCOL(sq) }, (o.hot || sq === "running" ? 0.8 : 0.42) * a, sq === "running" ? 0.6 : 0, [1.5, 3.5]);
    cx.beginPath(); cx.moveTo(A.x + nr, A.y); cx.bezierCurveTo(A.x + dx, A.y, B.x - dx, B.y, B.x - nr, B.y); cx.stroke(); cx.setLineDash([]); }
  for (const n of g.nodes) { const s = st(n.name), c = SCOL(s), idle = s === "not_started" || s === "skipped", X = x + n.x * sc, Y = y + n.y * sc;
    dot(X, Y, nr, rgba("#060a14", 0.92 * a)); circle(X, Y, nr, rgba(c, (idle ? 0.5 : 0.92) * a), (o.mini ? 0.8 : 1.15) / K ** 0.5);
    if (s !== "skipped") dot(X, Y, nr * 0.38, rgba(c, (idle ? 0.4 : 0.95) * a));
    if (o.hits) HITS.push({ x: X, y: Y, r: nr + 2, ref: ref("mgStep", `${k}:${n.name}`, { k, name: n.name }) });
    if (o.pulses) { const key = `${o.pulses}:${n.name}`, prev = SEEN.get(key); SEEN.set(key, s);
      if (prev && prev !== s && (s === "running" || s === "failed")) PUL.push({ x: X, y: Y, r: nr, t0: clock, col: s === "failed" ? RED : ACT, grow: 14 }); } }
  return { w: g.w * sc, h: g.h * sc, nr, root: { x: x + g.nodes[0].x * sc, y: y + g.nodes[0].y * sc } };
}
const glyphBox = (k, sc) => { const g = GL[k], nr = (g.nodes.length === 1 ? 5 : 4) * Math.sqrt(sc); return { w: g.w * sc + 2 * nr, h: g.h * sc + 2 * nr }; };
function drawFx() {
  for (let i = PUL.length - 1; i >= 0; i--) { const p = PUL[i], age = (clock - p.t0) / 1.2; if (age > 1.3) { PUL.splice(i, 1); continue; } if (age > 0) pulse(p.x, p.y, p.r, age, p.col, p.grow, [0, 0.18]); }
  for (let i = COM.length - 1; i >= 0; i--) { const c = COM[i], u = (clock - c.t0) / c.dur; if (u >= 1) { COM.splice(i, 1); continue; } comet(c.p0, c.c, c.p1, ease(u), 3.4, c.col); }
}
// the Board path the view hangs from: Review, the MERGED event on it, Done; the tasks in Review orbit it, a merged one ringed until MERGED
function drawPath(L) {
  const { rv, dn, mg } = L, p0 = { x: rv.x + rv.r + 6, y: rv.y }, p1 = { x: dn.x - dn.r - 8, y: dn.y }, heat = queue.some((q) => q.gone) ? 1 : 0;
  flow({ ...p0, color: BOARD_COLOR.review }, { ...p1, color: BOARD_COLOR.done }, 0.4 + heat * 0.45, heat);
  cx.beginPath(); cx.moveTo(p0.x, p0.y); cx.lineTo(p1.x, p1.y); cx.stroke(); cx.setLineDash([]); arrow(p0, p1, rgba(BOARD_COLOR.done, 0.6));
  for (const [s, id] of [[rv, "review"], [dn, "done"]]) { const r = ref("mgState", id, { id }), hot = hover === r; disc(s.x, s.y, s.r, BOARD_COLOR[id], hot, id === "done"); HITS.push({ x: s.x, y: s.y, r: s.r + 4, ref: r }); }
  const wait = queue.filter((q) => !q.merged).length, merged = queue.filter((q) => q.merged && !q.gone).length, n24 = merges.filter((m) => m.t > now() - 86400).length;
  const lab = (s, name, sub) => { if (L.labLeft && s === rv) { T_(name, s.x - s.r - 14, s.y - 7 * F, 13, INK(0.85), "right", 400); T_(sub, s.x - s.r - 14, s.y + 9 * F, 11, MUTED(), "right"); }
    else { T_(name, s.x, s.y + s.r + 16 * F, 13, INK(0.85), "center", 400); T_(sub, s.x, s.y + s.r + 32 * F, 11, MUTED(), "center"); } };
  lab(rv, "Review", `${wait} waiting to merge${merged ? ` · ${merged} merged` : ""}`); lab(dn, "Done", `${n24} merged in 24 h`);
  const hotMg = hover?.kind === "mgStep" || hover?.o === STAR.mf; dot(mg.x, mg.y, 4.5 / K ** 0.5, "rgba(6,10,20,0.95)"); circle(mg.x, mg.y, 4.5 / K ** 0.5, rgba(ACT, hotMg ? 1 : 0.7), 1.3 / K ** 0.5);
  T_("MERGED", mg.x, mg.y - 14 * F, 11, INK(0.8), "center", 500);
  queue.forEach((q, i) => { if (q.gone) return; const a = (i / Math.max(3, queue.length)) * TAU + clock * 0.25, R = rv.r + 9, x = rv.x + Math.cos(a) * R, y = rv.y + Math.sin(a) * R, hot = hover === q.ref;
    dot(x, y, hot ? 4.6 : 3, rgba(modelColor(q.t.model), 0.95)); if (q.merged) circle(x, y, 6, rgba(ACT, 0.9), 1.3);
    if (q.enter && clock - q.enter < 1.3) pulse(x, y, 3, (clock - q.enter) / 1.2, BOARD_COLOR.review, 16, [0]); HITS.push({ x, y, r: 7, ref: q.ref }); });
}
// merge to main: the junction every rail leaves from, tied to Review by the PR that merged
function drawJunction(L, labSide = "left") {
  const { J, rv } = L, m = merges[0], hot = hover?.kind === "mgJ", r = 6 / K ** 0.5;
  rail([{ x: rv.x, y: rv.y + rv.r + 4 }, { x: J.x, y: J.y - 9, c: { x: rv.x, y: (rv.y + J.y) / 2 } }].map((p, i) => (i ? p : p)), BOARD_COLOR.review, ACT, m && clock - (m.fresh || -9) < 2, false);
  cx.save(); cx.translate(J.x, J.y); cx.rotate(Math.PI / 4); cx.fillStyle = "rgba(6,10,20,0.95)"; cx.fillRect(-r, -r, 2 * r, 2 * r); cx.strokeStyle = rgba(ACT, hot ? 1 : 0.8); cx.lineWidth = 1.4 / K ** 0.5; cx.strokeRect(-r, -r, 2 * r, 2 * r); cx.restore();
  const al = labSide === "left" ? "right" : "left", lx = J.x + (labSide === "left" ? -16 : 16);
  T_("merge to main", lx, J.y - 7 * F, 12.5, INK(hot ? 1 : 0.85), al, 500); if (m) T_(`HEAD ${m.sha} · ${hhmm(m.t)} MST`, lx, J.y + 9 * F, 11, MUTED(), al);
  T_("PR merges", rv.x + (L.prLabRight ? 8 : -8), (rv.y + rv.r + J.y) / 2, 10.5, MUTED(0.55), L.prLabRight ? "left" : "right");
  HITS.push({ x: J.x, y: J.y, r: 12, ref: ref("mgJ", "J", {}) });
}
// the three DAGs as templates, coloured by the merge in focus (hovered, selected, else the newest)
function drawTemplates(L) {
  const m = focusM(), t = now(), out = {}, live = !(hover?.kind === "mgMerge" || panelSel());
  for (const k of KS) { const p = L.tpl[k], b = glyphBox(k, p.sc), hot = hover?.o === STAR[k] || hover?.o?.k === k;
    HITS.push({ x0: p.x - b.w / 2 - 6, y0: p.y - b.h / 2 - 6, x1: p.x + b.w / 2 + 6, y1: p.y + b.h / 2 + 6, ref: ref("dag", k, STAR[k]) });
    const r = m?.runs[k], g = drawGlyph(k, p.x, p.y, p.sc, (n) => stepSt(r, n, t), { hits: true, hot, pulses: live ? `T${k}` : null }); out[k] = g;
    if (runningAny(k)) { const glow = cx.createRadialGradient(p.x, p.y, 0, p.x, p.y, Math.max(b.w, b.h) * 0.8); glow.addColorStop(0, rgba(ACT, 0.07)); glow.addColorStop(1, rgba(ACT, 0)); cx.fillStyle = glow; cx.beginPath(); cx.arc(p.x, p.y, Math.max(b.w, b.h) * 0.8, 0, TAU); cx.fill(); }
    const ly = p.y + b.h / 2 + 14 * F, st = r ? runSt(r, t) : null, ax = p.capX ?? p.x, al = p.capX !== undefined ? "left" : "center";
    T_(NM[k], ax, ly, 12, INK(hot ? 1 : 0.85), al, 500);
    T_(k === "mf" ? "on push · every 5 min" : "cue · each merge to main", ax, ly + 15 * F, 10.5, MUTED(0.6), al);
    if (m) T_(r ? `${m === merges[0] ? "newest" : hhmm(m.t)} ${m.sha} · ${st === "running" ? `running ${curStep(r, t) || ""}` : st === "queued" ? "waiting to start" : st === "failed" ? `✕ ${r.fail}` : `✓ ${dur(r.dur)}`}` : `${hhmm(m.t)} ${m.sha} · no run: other repo`, ax, ly + 30 * F, 10.5, rgba(SCOL(st || "waiting"), 0.85), al); }
  // main-follow writes MERGED on the path; the 5-minute schedule feeds it as well as each push
  const mf = L.tpl.mf, n = out.mf; line([{ x: mf.x, y: mf.y - n.nr - 3 }, { x: L.mg.x, y: L.mg.y + 6 }], rgba(ACT, 0.7), 1.2, [2, 4]);
  T_("writes MERGED", mf.x + 8, (mf.y + L.mg.y) / 2 + 6 * F, 10.5, rgba(ACT, 0.8), "left");
  const ck = { x: mf.x + n.nr + 40 * F, y: mf.y }; circle(ck.x, ck.y, 6 / K ** 0.5, MUTED(0.7), 1 / K ** 0.5); line([ck, { x: ck.x, y: ck.y - 3.5 / K ** 0.5 }], MUTED(0.8)); line([ck, { x: ck.x + 2.6 / K ** 0.5, y: ck.y }], MUTED(0.8));
  line([{ x: ck.x - 8 / K ** 0.5, y: ck.y }, { x: mf.x + n.nr + 3, y: mf.y }], MUTED(0.45), 1, [1.5, 4]); T_("5 min", ck.x + 10 / K ** 0.5, ck.y, 10.5, MUTED(0.6));
  return out;
}
const statusLine = (m, k, t) => { const r = m.runs[k]; if (!r) return [m.bump ? `applied by its pin bump ${m.bump.sha}` : "waits for its pin bump", m.bump ? hhmm(m.bump.t) + " MST" : "", "waiting"];
  const st = runSt(r, t), main = st === "queued" ? `starts in ${dur(r.start - t)}` : st === "running" ? `${curStep(r, t) || "running"} · ${dur(t - r.start)}` : st === "failed" ? `✕ ${r.fail} · ${dur(r.dur)}` : `✓ ${dur(r.dur)}`;
  const sub = k === "mf" ? (t >= m.mergedAt ? `MERGED ${hhmm(m.mergedAt)}${m.cross ? " · 5-min pass" : ""}` : m.cross ? `5-min pass ${hhmm(r.start)}` : "MERGED next") : k === "aom" ? shortApplied(r) : `${hhmm(r.start)} MST`;
  return [main, sub, st]; };
// the 24-hour strip: one tick per merge, red where an apply failed (bright while unresolved), purple for another repo's merge
function drawStrip(L) {
  const s = L.strip, t = now(), X = (tt) => s.x0 + ((tt - (t - 86400)) / 86400) * (s.x1 - s.x0), pins = new Set(pinnedAt(t));
  line([{ x: s.x0, y: s.y }, { x: s.x1, y: s.y }], MUTED(0.18));
  for (let h = Math.ceil((t - 86400) / 3600) * 3600; h <= t; h += 3600) { const x = X(h); line([{ x, y: s.y + s.h / 2 + 2 }, { x, y: s.y + s.h / 2 + 5 }], MUTED(0.3)); if (mstHour(h) % 3 === 0) T_(hhmm(h), x, s.y + s.h / 2 + 14 * F, 10, MUTED(0.5), "center"); }
  T_(`last 24 h · ${merges.filter((m) => m.t > t - 86400).length} merges`, s.x0, s.y - s.h / 2 - 12 * F, 10.5, MUTED(0.7));
  if (L.shown?.length) { const a = X(Math.min(...L.shown.map((m) => m.t))), b = X(Math.max(...L.shown.map((m) => m.t))); cx.fillStyle = rgba(ACT, 0.06); cx.fillRect(a - 3, s.y - s.h / 2 - 3, b - a + 6, s.h + 6);
    T_(L.shownLabel || "shown above", b, s.y - s.h / 2 - 12 * F, 10, rgba(ACT, 0.6), "right"); }
  for (const m of merges) { if (m.t < t - 86400) continue; const x = X(m.t), hot = hover === m.ref || panelSel() === m;
    if (s.dots) KS.forEach((k, i) => { const r = m.runs[k], st = r ? runSt(r, t) : "waiting"; dot(x, s.y + (i - 1) * 7 * Math.min(1.4, F), hot ? 2.6 : 1.8, rgba(SCOL(st), st === "succeeded" ? 0.6 : 0.95)); });
    else { const w = worst(m, t), col = m.cross ? CROSS : SCOL(w), al = w === "failed" ? (pins.has(m) ? 1 : 0.5) : w === "succeeded" ? 0.5 : 0.95; line([{ x, y: s.y - s.h / 2 }, { x, y: s.y + s.h / 2 }], rgba(col, hot ? 1 : al), hot ? 2.2 : 1.2); }
    if (pins.has(m)) star4(x, s.y - s.h / 2 - 6, 4.5, RED); }
  for (const r of RERUNS) if (r.start > t - 86400 && r.start <= t) { const x = X(r.start), done = t >= r.end; T_("↻", x, s.y + s.h / 2 + 3 * F + 7, 11, rgba(done ? DAG_COLOR.succeeded : ACT, 0.9), "center", 500);
    HITS.push({ x, y: s.y + s.h / 2 + 10, r: 7, ref: r.ref }); }
  HITS.push({ x0: s.x0 - 4, y0: s.y - s.h / 2 - 8, x1: s.x1 + 4, y1: s.y + s.h / 2 + 4, pick: (x) => { let b = null, bd = 8 / K; for (const m of merges) { const d = Math.abs(X(m.t) - x); if (m.t > t - 86400 && d < bd) { bd = d; b = m; } } return b?.ref; } });
}

// ---- C: Ledger. Main's history is a spine under Review; each merge is a row hung from it, with its own copy of each DAG's figure in
// that DAG's column, so the rows and the templates make one grid. Unresolved failures pin above the spine's newest merge ----
function layC() {
  const f = F, L = { labLeft: true };
  L.lt = Math.min(340 * f, W * 0.26); L.sx = 64 + L.lt; L.lane = L.sx + 22 * f;
  L.yP = 62 * f; L.rv = { x: L.sx, y: L.yP, r: 22 }; L.dn = { x: W - 40 - 60 * f, y: L.yP, r: 22 };
  const c0 = L.sx + 46 * f, avail = W - 70 - c0; L.cols = { mf: { x0: c0, w: avail * 0.24 }, aom: { x0: c0 + avail * 0.24, w: avail * 0.44 }, gr: { x0: c0 + avail * 0.68, w: avail * 0.32 } };
  L.msc = { mf: 0.8, aom: 0.3, gr: 0.55 }; const tsc = { mf: 1, aom: 0.72, gr: 1.1 }, aomH = glyphBox("aom", tsc.aom).h;
  L.yH = L.yP + 64 * f + aomH / 2; L.J = { x: L.sx, y: L.yH };
  L.tpl = {}; for (const k of KS) { const b = glyphBox(k, tsc[k]); L.tpl[k] = { x: L.cols[k].x0 + 14 + b.w / 2, y: L.yH, sc: tsc[k] }; }
  L.mg = { x: L.tpl.mf.x, y: L.yP }; L.yB = L.yH + aomH / 2 + 56 * f;
  L.rh = Math.max(glyphBox("aom", L.msc.aom).h + 12, 34 * f); L.yR0 = L.yB + 26 * f + L.rh / 2;
  const bottom = H - 70 * f - 14; L.strip = { x0: L.sx, x1: W - 70, y: bottom - 30 * f, h: 18 * f }; L.yEnd = L.strip.y - 44 * f;
  L.cap = Math.max(2, Math.floor((L.yEnd - L.yR0 + L.rh / 2) / L.rh)); L.dn.r = 22; L.prLabRight = false;
  return L;
}
function drawC(L) {
  const t = now(), pins = pinnedAt(t), gap = pins.length ? 18 * F : 0, rest = merges.filter((m) => !pins.includes(m)), room = L.cap - (gap ? 1 : 0);
  const showPins = pins.slice(0, Math.max(1, Math.min(pins.length, Math.floor(room / 2)))), rows = [...showPins, ...rest.slice(0, Math.max(0, room - showPins.length))];
  L.shown = rows.filter((m) => !pins.includes(m)); L.shownLabel = `newest ${L.shown.length} shown above`;
  const target = new Map(rows.map((m, i) => [m, L.yR0 + i * L.rh + (i >= showPins.length ? gap : 0)])), dt = Math.min(0.1, clock - lastClock);
  for (const m of rows) { const y = target.get(m); m._y = m._y === undefined || m._gone ? y - (m.fresh && clock - m.fresh < 1 ? L.rh : 0) : m._y + (y - m._y) * Math.min(1, dt * 7); m._gone = false; }
  for (const m of merges) if (!target.has(m)) m._gone = true;
  const yLast = (rows.at(-1)?._y ?? L.yR0) + L.rh / 2, x1 = W - 60;
  // the grid: columns down from each template, a hairline between rows, the spine (main) and the lane for other repos' merges
  for (const k of KS) line([{ x: L.cols[k].x0, y: L.yH - 50 * F }, { x: L.cols[k].x0, y: yLast }], MUTED(0.1));
  line([{ x: L.sx, y: L.J.y + 8 }, { x: L.sx, y: yLast }], rgba(ACT, 0.35), 1.4);
  line([{ x: L.lane, y: L.yR0 - L.rh / 2 }, { x: L.lane, y: yLast }], rgba(CROSS, 0.35), 1, [2, 4]); T_("other repos", L.lane + 4, L.yR0 - L.rh / 2 - 9 * F, 9.5, rgba(CROSS, 0.6));
  if (showPins.length) { const y0 = showPins[0]._y - L.rh / 2, y1 = showPins.at(-1)._y + L.rh / 2; cx.fillStyle = rgba(RED, 0.05); cx.fillRect(64, y0, x1 - 64, y1 - y0); line([{ x: L.sx, y: y0 }, { x: L.sx, y: y1 }], rgba(RED, 0.7), 2);
    T_(`UNRESOLVED · ${pins.length} failed apply${pins.length > 1 ? "s" : ""}${pins.length > showPins.length ? ` (${pins.length - showPins.length} more on the strip)` : ""}`, 64, y0 - 9 * F, 10, rgba(RED, 0.9), "left", 500);
    const rr = RERUNS.find((r) => t >= r.start && t < r.end); if (rr) T_(`↻ forced rerun running · ${dur(t - rr.start)}`, x1, y0 - 9 * F, 10, ACT, "right", 500); }
  const T = drawTemplates(L);
  // rails: main-follow on push, straight from the junction; apply-on-merge and graph-refresh cued off a bus under the templates
  const mfn = T.mf; rail([{ x: L.J.x + 9, y: L.J.y }, { x: mfn.root.x - mfn.nr - 3, y: mfn.root.y }], ACT, ACT, runningAny("mf"));
  T_("on push", (L.J.x + mfn.root.x) / 2, L.J.y - 9 * F, 10.5, MUTED(0.6), "center");
  for (const k of ["aom", "gr"]) { const r = T[k].root; rail([{ x: L.sx, y: L.yB }, { x: r.x - 40, y: L.yB }, { x: r.x - T[k].nr - 2, y: r.y, c: { x: r.x - 14, y: L.yB } }], ACT, ACT, runningAny(k), true); }
  T_("cue · each merge to main", L.sx + 10, L.yB - 8 * F, 10, MUTED(0.55));
  drawPath(L); drawJunction(L);
  for (const m of rows) drawRowC(L, m, pins.includes(m), t);
  for (const m of rows) if (m.cross && m.bump && target.has(m.bump)) { const a = { x: L.lane, y: m._y }, b = { x: L.sx, y: m.bump._y };
    line([a, b].length && [a, { x: b.x + 4, y: b.y }], rgba(CROSS, 0.6), 1, [2, 3]); T_("pin bump", (a.x + b.x) / 2 + 6, (a.y + b.y) / 2, 9.5, rgba(CROSS, 0.7)); }
  drawStrip(L);
}
function drawRowC(L, m, pin, t) {
  const y = m._y, a = m._a ?? 1, hot = hover === m.ref || panelSel() === m, x1 = W - 60, f = F;
  if (hot) { cx.fillStyle = "rgba(219,228,243,0.045)"; cx.fillRect(64, y - L.rh / 2 + 1, x1 - 64, L.rh - 2); }
  line([{ x: L.sx, y: y + L.rh / 2 }, { x: x1, y: y + L.rh / 2 }], MUTED(0.07));
  HITS.push({ x0: 64, y0: y - L.rh / 2, x1, y1: y + L.rh / 2, ref: m.ref });
  if (pin) star4(L.sx, y, 6.5, RED); else if (m.cross) { dot(L.lane, y, 3.6 / K ** 0.5, "rgba(6,10,20,1)"); circle(L.lane, y, 3.6 / K ** 0.5, rgba(CROSS, 0.9 * a), 1.3 / K ** 0.5); line([{ x: L.sx, y }, { x: L.lane - 4, y }], rgba(CROSS, 0.25)); }
  else { dot(L.sx, y, 3.4 / K ** 0.5, rgba(ACT, 0.85 * a)); if (m.fresh && clock - m.fresh < 1.3) pulse(L.sx, y, 3.4, (clock - m.fresh) / 1.2, ACT, 22, [0]); }
  const who = m.task?.id || (m.bumpOf ? "pin bump" : "—"), lw = L.lt - 10;
  T_(clip(`${hhmm(m.t)}  ${who}`, lw, 12.5, 500), 64, y - 8 * f, 12.5, pin ? rgba(RED, a) : INK(0.92 * a), "left", 500);
  cx.font = `500 ${(12.5 * f) / K}px Inter, system-ui, sans-serif`; const used = cx.measureText(`${hhmm(m.t)}  ${who}`).width + 8 * f;
  if (used < lw - 40 * f) T_(clip(`${m.repo} #${m.pr} · ${m.sha}`, lw - used, 10.5), 64 + used, y - 8 * f, 10.5, MUTED(0.6 * a));
  T_(clip(m.title, lw, 11), 64, y + 9 * f, 11, MUTED(0.7 * a));
  for (const k of KS) { const c = L.cols[k], gx = L.tpl[k].x, [main, sub, st] = statusLine(m, k, t); let tx = c.x0 + 14;
    if (m.runs[k]) { const g = drawGlyph(k, gx, y, L.msc[k], (n) => stepSt(m.runs[k], n, t), { mini: true, alpha: a, pulses: `${m.sha}${k}` }); tx = Math.max(gx + g.w / 2 + g.nr + 12, c.x0 + 30 * f); }
    const room = c.x0 + c.w - tx - 10; T_(clip(main, room, 11.5, 500), tx, y - 7 * f, 11.5, rgba(SCOL(st), st === "succeeded" ? 0.85 * a : a), "left", 500);
    if (sub) T_(clip(sub, room, 10.5), tx, y + 8 * f, 10.5, MUTED(0.6 * a)); }
}

// ---- A: Junction. The causal sequence large across the top, the templates the one constellation; below it the 24-hour strip, every
// merge three dots (main-follow, apply-on-merge, graph-refresh), and a ledger of the newest merges in plain rows ----
function layA() {
  const f = F, L = { prLabRight: true };
  L.yP = 62 * f; L.rv = { x: 40 + 90 * f, y: L.yP, r: 24 }; L.dn = { x: W - 40 - 60 * f, y: L.yP, r: 24 };
  L.J = { x: W * 0.2, y: L.yP + 120 * f }; const tsc = { mf: 1.2, aom: 1.15, gr: 1.8 }, aomH = glyphBox("aom", tsc.aom).h;
  L.tpl = { mf: { x: W * 0.6, y: L.J.y, sc: tsc.mf }, aom: { x: W * 0.38, y: L.J.y + 70 * f + aomH / 2, sc: tsc.aom }, gr: { x: W * 0.72, y: L.J.y + 70 * f + aomH / 2, sc: tsc.gr } };
  L.mg = { x: L.tpl.mf.x, y: L.yP };
  const yS = L.tpl.aom.y + aomH / 2 + 82 * f; L.strip = { x0: 110, x1: W - 90, y: yS, h: 24 * Math.min(1.4, f), dots: true };
  L.yL = yS + L.strip.h / 2 + 52 * f; L.rh = 25 * f; L.cap = Math.max(2, Math.floor((H - 70 * f - 20 - L.yL) / L.rh));
  return L;
}
function drawA(L) {
  const t = now(), T = drawTemplates(L), J = L.J;
  rail([{ x: J.x + 9, y: J.y }, { x: T.mf.root.x - T.mf.nr - 3, y: T.mf.root.y }], ACT, ACT, runningAny("mf")); T_("on push", (J.x + T.mf.root.x) / 2, J.y - 9 * F, 10.5, MUTED(0.6), "center");
  for (const k of ["aom", "gr"]) { const r = T[k].root; rail([{ x: J.x, y: J.y + 9 }, { x: r.x - T[k].nr - 2, y: r.y, c: { x: J.x + 10, y: r.y } }], ACT, ACT, runningAny(k), true); }
  T_("cue", J.x + 18, J.y + 40 * F, 10, MUTED(0.55));
  drawPath(L); drawJunction(L);
  const pins = pinnedAt(t), rows = [...pins.slice(0, Math.ceil(L.cap / 2)), ...merges.filter((m) => !pins.includes(m))].slice(0, L.cap);
  L.shown = rows.filter((m) => !pins.includes(m)); L.shownLabel = `newest ${L.shown.length} listed below`;
  drawStrip(L);
  const cols = { tm: 110, id: 160 * F + 22, title: 250 * F + 30, pr: W * 0.47, mf: W * 0.58, aom: W * 0.7, gr: W * 0.84 };
  T_("NEWEST MERGES", 110, L.yL - 22 * F, 10, MUTED(0.6), "left", 500);
  KS.forEach((k) => T_(NM[k], cols[k], L.yL - 22 * F, 10, MUTED(0.6), "left", 500));
  rows.forEach((m, i) => { const y = L.yL + i * L.rh + (i >= Math.min(pins.length, Math.ceil(L.cap / 2)) && pins.length ? 8 * F : 0), pin = pins.includes(m), hot = hover === m.ref || panelSel() === m;
    if (hot) { cx.fillStyle = "rgba(219,228,243,0.05)"; cx.fillRect(96, y - L.rh / 2, W - 186, L.rh); }
    if (pin) { cx.fillStyle = rgba(RED, 0.06); cx.fillRect(96, y - L.rh / 2, W - 186, L.rh); star4(100, y, 5, RED); } else dot(100, y, 2.6, rgba(m.cross ? CROSS : ACT, 0.8));
    HITS.push({ x0: 96, y0: y - L.rh / 2, x1: W - 90, y1: y + L.rh / 2, ref: m.ref });
    T_(hhmm(m.t), cols.tm, y, 11.5, INK(0.85)); T_(clip(m.task?.id || (m.bumpOf ? "pin bump" : "—"), cols.title - cols.id - 8, 11.5, 500), cols.id, y, 11.5, pin ? RED : INK(0.92), "left", 500);
    T_(clip(m.title, cols.pr - cols.title - 12, 11), cols.title, y, 11, MUTED(0.75)); T_(clip(`${m.repo} #${m.pr} · ${m.sha}`, cols.mf - cols.pr - 10, 10.5), cols.pr, y, 10.5, MUTED(0.6));
    for (const k of KS) { const [main, , st] = statusLine(m, k, t), x = cols[k], nx = k === "gr" ? W - 100 : cols[KS[KS.indexOf(k) + 1]];
      dot(x + 3, y, 2.6, rgba(SCOL(st), 0.95)); T_(clip(main, nx - x - 22, 11), x + 12, y, 11, rgba(SCOL(st), st === "succeeded" ? 0.8 : 1)); } });
}

// ---- B: Orrery. The three DAGs a triad around the junction; every merge of the last day orbits Done on a ring by age, ringed by three
// arcs (main-follow, apply-on-merge, graph-refresh); an unresolved failure is a red star on the innermost ring until it clears ----
function layB() {
  const f = F, L = {}; L.yP = H * 0.36; const outer = Math.min(250, L.yP - 40, (W - W * 0.66) - 60, (H - 70 * f - 20 - L.yP) - 20);
  L.dn = { x: W - outer - 60, y: L.yP, r: Math.max(22, outer * 0.15) }; L.rv = { x: 40 + 90 * f, y: L.yP, r: 24 };
  const R0 = L.dn.r + 34 + 14 * f; L.pinR = L.dn.r + 12; const span = outer - R0;
  L.rings = [[0, 3600, "last hour"], [3600, 4 * 3600, "1–4 h"], [4 * 3600, 12 * 3600, "4–12 h"], [12 * 3600, 86400, "12–24 h"]].map(([a0, a1, name], i) => ({ a0, a1, name, R: R0 + 12 + (span - 12) * (i / 3) }));
  L.mg = { x: L.dn.x - outer - 120 - 40 * f, y: L.yP };
  L.J = { x: Math.min(W * 0.22, L.mg.x - 360), y: L.yP + 120 * f };
  const aomB = glyphBox("aom", 0.95); L.tpl = { mf: { x: L.mg.x, y: L.J.y, sc: 1.2 }, aom: { x: Math.max(110 + aomB.w / 2, L.J.x - 60), y: L.J.y + 70 * f + aomB.h / 2, sc: 0.95 }, gr: { x: L.J.x + 150 + 120 * f, y: L.J.y + 70 * f + aomB.h / 2, sc: 1.6 } };
  return L;
}
function drawB(L) {
  const t = now(), T = drawTemplates(L), J = L.J, dn = L.dn, pins = pinnedAt(t);
  rail([{ x: J.x + 9, y: J.y }, { x: T.mf.root.x - T.mf.nr - 3, y: T.mf.root.y }], ACT, ACT, runningAny("mf")); T_("on push", (J.x + T.mf.root.x) / 2, J.y - 9 * F, 10.5, MUTED(0.6), "center");
  for (const k of ["aom", "gr"]) { const r = T[k].root; rail([{ x: J.x, y: J.y + 9 }, { x: r.x - T[k].nr - 2, y: r.y, c: { x: J.x, y: r.y } }], ACT, ACT, runningAny(k), true); }
  for (const g of L.rings) { circle(dn.x, dn.y, g.R, MUTED(0.12), 1 / K ** 0.5); T_(g.name, dn.x + 4, dn.y - g.R - 7 * F, 9.5, MUTED(0.5), "left"); }
  if (pins.length) { circle(dn.x, dn.y, L.pinR, rgba(RED, 0.35), 1 / K ** 0.5, [2 / K, 3 / K]); }
  drawPath(L); drawJunction(L);
  const posOf = (m) => { const age = t - m.t, g = L.rings.find((r) => age >= r.a0 && age < r.a1); if (!g) return null; const th = -Math.PI / 2 + (TAU * (age - g.a0)) / (g.a1 - g.a0); return { x: dn.x + Math.cos(th) * g.R, y: dn.y + Math.sin(th) * g.R }; };
  for (const m of merges) { const p = posOf(m); if (!p) continue; m._p = p; const hot = hover === m.ref || panelSel() === m, a = m._a ?? 1;
    KS.forEach((k, i) => { const r = m.runs[k], st = r ? runSt(r, t) : "waiting", a0 = -Math.PI / 2 + (i * TAU) / 3 + 0.18, R = (hot ? 7.5 : 5.5) / K ** 0.5;
      cx.strokeStyle = rgba(SCOL(st), (st === "succeeded" ? 0.6 : 1) * a); cx.lineWidth = (hot ? 2.4 : 1.8) / K ** 0.5; cx.beginPath(); cx.arc(p.x, p.y, R, a0, a0 + TAU / 3 - 0.36); cx.stroke(); });
    dot(p.x, p.y, (hot ? 3.2 : 2.2) / K ** 0.5, rgba(m.cross ? CROSS : ACT, 0.9 * a)); if (m.fresh && clock - m.fresh < 1.3) pulse(p.x, p.y, 3, (clock - m.fresh) / 1.2, ACT, 22, [0]);
    HITS.push({ x: p.x, y: p.y, r: 9, ref: m.ref }); }
  for (const m of merges) if (m.cross && m.bump && m._p && m.bump._p) line([m._p, m.bump._p], rgba(CROSS, 0.45), 1, [2, 3]);
  pins.forEach((m, i) => { const th = -Math.PI / 2 - 0.5 + i * (TAU / Math.max(8, pins.length)), p = { x: dn.x + Math.cos(th) * L.pinR, y: dn.y + Math.sin(th) * L.pinR }, hot = hover === m.ref || panelSel() === m;
    if (m._p) line([p, m._p], rgba(RED, hot ? 0.8 : 0.3), 1, [2, 3]); star4(p.x, p.y, hot ? 8 : 6, RED); HITS.push({ x: p.x, y: p.y, r: 9, ref: m.ref }); });
  if (pins.length) T_(`${pins.length} unresolved`, dn.x, dn.y + dn.r + 50 * F, 10.5, rgba(RED, 0.9), "center", 500);
  const rr = RERUNS.find((r) => t >= r.start && t < r.end); if (rr) T_(`↻ forced rerun running · ${dur(t - rr.start)}`, dn.x, dn.y - L.pinR - 22 * F, 10, ACT, "center", 500);
  T_("each merge orbits Done by age · arcs: main-follow, apply-on-merge, graph-refresh", dn.x, dn.y + L.rings.at(-1).R + 20 * F, 10, MUTED(0.55), "center");
}

const LAY = { a: layA, b: layB, c: layC }, DRAW = { a: drawA, b: drawB, c: drawC };

// ---- hooks into the page: this path's fold level only; every other level keeps the page's own code ----
const _buildFold = buildFold, _drawFold = drawFold, _hit = hit, _tipHtml = tipHtml, _click = click;
buildFold = function (l) { if (!mine(l)) return _buildFold(l); F = rootFs(); Object.assign(scene, { w: W, h: H, box: [W * 0.03, H * 0.03, W * 0.97, H * 0.97], fold: null }); scene.mg = LAY[VAR](); };
drawFold = function () { if (!scene.mg) return _drawFold(); HITS = []; tick(); DRAW[VAR](scene.mg); drawFx(); lastClock = clock; };
hit = function (x, y) {
  if (!scene.mg) return _hit(x, y);
  for (let i = HITS.length - 1; i >= 0; i--) { const h = HITS[i];
    if (h.r !== undefined ? Math.hypot(h.x - x, h.y - y) < Math.max(h.r, px(5)) : x >= h.x0 && x <= h.x1 && y >= h.y0 && y <= h.y1) { const r = h.pick ? h.pick(x) : h.ref; if (r) return r; } }
  return null;
};
const runRow = (m, k, t) => { const [main, sub, st] = statusLine(m, k, t); return `<div style="color:${SCOL(st)}">${esc(NM[k])}: ${esc(main)}${sub ? ` <span class="k">· ${esc(sub)}</span>` : ""}</div>`; };
tipHtml = function (h) {
  tip.classList.toggle("mg", !!scene.mg); if (!scene.mg || !h.kind.startsWith("mg")) return _tipHtml(h);
  const t = now(), o = h.o;
  if (h.kind === "mgMerge") { const res = o.runs.aom?.fail && t >= o.runs.aom.end ? resolver(o, t) : null;
    return `<div class="k">${o.bumpOf ? `pin bump for ${esc(o.bumpOf.repo)} #${o.bumpOf.pr}` : `merge to ${esc(o.repo)}`} · ${hms(o.t)} MST · #${o.pr} · ${esc(o.sha)}</div><div class="n">${esc(o.task?.id || "pin bump")}</div>${esc(o.title)}
      ${KS.map((k) => runRow(o, k, t)).join("")}${o.runs.aom?.fail && t >= o.runs.aom.end ? `<div class="k" style="color:${res ? DAG_COLOR.succeeded : RED}">${res ? `resolved ${hhmm(res.at)} MST by ${esc(res.by)}` : `unresolved: a later merge applies only its own diff, so ${esc(o.runs.aom.fail)} stays unapplied until a forced rerun`}</div>` : ""}
      ${o.cross ? `<div class="k">another repo's merge: main-follow's 5-minute pass writes MERGED; nothing applies until the trantor pin bump</div>` : ""}<div class="k">click for its runs</div>`; }
  if (h.kind === "mgStep") { const m = focusM(), r = m?.runs[o.k], deps = dagBy[NM[o.k]].steps.find((s) => s.name === o.name).depends;
    return `<div class="k">step of ${esc(NM[o.k])}${deps.length ? ` · after ${deps.map(esc).join(", ")}` : ""}</div><div class="n">${esc(o.name)}</div>${m ? `${esc(stepSt(r, o.name, t).replace("_", " "))} in ${m === merges[0] ? "the newest merge" : `the ${hhmm(m.t)} merge`} (${esc(m.sha)})` : ""}<div class="k">hover a merge to see its run here · click for the DAG</div>`; }
  if (h.kind === "mgJ") return `<div class="k">merge to main · ${merges.filter((m) => m.t > t - 3600).length} in the last hour</div><div class="n">A PR merges</div>main-follow runs on the push and writes MERGED, moving the task Review → Done. The merge also cues apply-on-merge and graph-refresh, which apply and index it.`;
  if (h.kind === "mgQ") return `<div class="k">task in Review</div><div class="n">${esc(o.t.id)}</div>${esc(o.t.title)}<div class="k">${o.merged ? `PR merged ${hhmm(o.merged.t)} MST · waiting for main-follow to write MERGED` : "waiting for its PR to merge"}</div>`;
  if (h.kind === "mgState") return `<div class="k">Board state · click to open</div><div class="n">${esc(stateName(o.id))}</div>${board.agents.filter((a) => a.state === o.id).length} tasks at snapshot`;
  if (h.kind === "mgRerun") return `<div class="k">forced apply-on-merge rerun · ${hms(o.start)} MST</div><div class="n">${t >= o.end ? `✓ ${dur(o.dur)}` : `running · ${dur(t - o.start)}`}</div>reapplies everything since the last good apply, clearing every failure before it`;
  return "";
};
function openMerge(m) {
  sel = m; const t = now(), res = m.runs.aom?.fail && t >= m.runs.aom.end ? resolver(m, t) : null, unres = m.runs.aom?.fail && t >= m.runs.aom.end && !res;
  const runs = KS.map((k) => { const r = m.runs[k]; if (!r) return `<tr><td>${esc(NM[k])}</td><td class="k">${m.bump ? `no run: applied by its pin bump ${esc(m.bump.sha)} at ${hhmm(m.bump.t)} MST` : "no run: waits for its pin bump"}</td></tr>`;
    const st = runSt(r, t), chips = STEPS[k].map((n) => { const s = stepSt(r, n, t), c = SCOL(s); return `<span class="chip" style="color:${c};border-color:${rgba(c, 0.4)}" title="${esc(s)}">${esc(n)}</span>`; }).join(" ");
    return `<tr><td>${esc(NM[k])}</td><td><b style="color:${SCOL(st)}">${st === "queued" ? "waiting to start" : esc(st)}</b> · ${hms(r.start)}${t >= r.end ? `–${hms(r.end)} MST · ${dur(r.dur)}` : " MST"}${k === "aom" ? `<div class="k">applied: ${esc(shortApplied(r))}</div>` : ""}<div class="steps">${chips}</div></td></tr>`; }).join("");
  panel.className = "mg open";
  panel.innerHTML = `<span class="x">✕</span><div class="k">${m.bumpOf ? `pin bump for ${esc(m.bumpOf.repo)} #${m.bumpOf.pr}` : `merge to ${esc(m.repo)}`} · ${hms(m.t)} MST</div><h2>${esc(m.task?.id || "pin bump")} — ${esc(m.title)}</h2>
    <table><tr><td>Commit</td><td>${esc(m.repo)} #${m.pr} · ${esc(m.sha)}</td></tr>
    <tr><td>Board</td><td>${t >= m.mergedAt ? `Review → Done: main-follow wrote MERGED ${hms(m.mergedAt)} MST, ${dur(m.mergedAt - m.t)} after the merge` : "in Review until main-follow writes MERGED"}</td></tr>
    ${m.cross ? `<tr><td>Other repo</td><td>Its merge starts no run here. ${m.bump ? `The pin bump ${esc(m.bump.sha)} applied it at ${hhmm(m.bump.t)} MST.` : "It applies when trantor's pin bump merges."}</td></tr>` : ""}${runs}</table>
    ${unres ? `<div class="note" style="color:${RED}">Unresolved: a later merge applies only its own diff, so ${esc(m.runs.aom.fail)} stays unapplied until a forced rerun.</div><button class="run" id="mgRerun">↻ Force rerun apply-on-merge</button>` : res ? `<div class="note" style="color:${DAG_COLOR.succeeded}">Resolved ${hhmm(res.at)} MST by ${esc(res.by)}.</div>` : ""}
    <div class="note">Open on board ↗ · PR ↗ · Dagu run ↗ (the build slice links them)</div>`;
  panel.querySelector(".x").onclick = () => { panel.classList.remove("open"); sel = null; };
  panel.querySelector("#mgRerun")?.addEventListener("click", forceRerun);
}
function forceRerun() { if (RERUNS.some((r) => now() < r.end)) return; const r = { start: now() + 1, dur: 40, upto: now() }; r.end = r.start + r.dur; r.ref = { kind: "mgRerun", o: r }; RERUNS.push(r); deployBroken = false; panel.classList.remove("open"); sel = null; }
click = function (fx, fy) {
  if (!scene.mg) return _click(fx, fy);
  const h = hover; if (!h?.kind.startsWith("mg")) { panel.className = ""; sel = null; return _click(fx, fy); }
  if (h.kind === "mgMerge") return openMerge(h.o);
  if (h.kind === "mgState") return push({ kind: "state", id: h.o.id }, fx, fy);
  if (h.kind === "mgStep") { panel.className = ""; return openDagPanel(STAR[h.o.k]); }
  if (h.kind === "mgQ" && h.o.merged) return openMerge(h.o.merged);
};

// ---- design-review controls: the view, the scenario and the text size, each a linkable address ----
document.head.insertAdjacentHTML("beforeend", `<style>
#mctl { position: fixed; z-index: 4; left: calc(var(--nav) + 16px); right: calc(var(--rail) + 16px); bottom: 10px; display: flex; flex-wrap: wrap; gap: .375rem; align-items: center; justify-content: center; font-size: .6875rem; color: var(--muted); }
#mctl button { all: unset; cursor: pointer; white-space: nowrap; padding: .2rem .55rem; border-radius: 5px; border: 1px solid rgba(148,163,184,.25); color: var(--muted); background: rgba(6,10,20,.85); }
#mctl button:hover { color: var(--ink); } #mctl button.on { color: #fbbf24; border-color: #fbbf24; }
#mctl .g { margin-left: .6rem; letter-spacing: .14em; text-transform: uppercase; font-size: .625rem; } #mctl .note { flex-basis: 100%; text-align: center; }
#panel.mg { font-size: .75rem; width: 26rem; } #panel.mg h2 { font-size: .875rem; } #panel.mg .k, #panel.mg .note { font-size: .6875rem; }
#panel.mg td:first-child { white-space: nowrap; vertical-align: top; padding-right: .6rem; color: var(--muted); } #panel.mg .steps { margin-top: .25rem; line-height: 1.9; }
#panel.mg .chip { display: inline-block; padding: 0 .35rem; border: 1px solid; border-radius: 4px; font-size: .625rem; line-height: 1.5; }
#tip.mg { font-size: .75rem; max-width: 24rem; } #tip.mg .k { font-size: .6875rem; }
</style>`);
document.body.insertAdjacentHTML("beforeend", '<div id="mctl" hidden></div>');
const ctl = document.getElementById("mctl"), addr = (k, v) => { const q = new URLSearchParams(location.search); q.set(k, v); return `?${q}`; };
function renderCtl() {
  const ts = Math.round(rootFs() * 100), b = (on, attrs, label) => `<button class="${on ? "on" : ""}" ${attrs}>${label}</button>`;
  ctl.innerHTML = `<span class="g">View</span>${Object.entries(VARS).map(([k, n]) => b(k === VAR, `data-go="${addr("merged", k)}"`, `${k.toUpperCase()} · ${n}`)).join("")}
    <span class="g">Scenario</span>${Object.keys(SCNS).map((k) => b(k === SCN, `data-go="${addr("ms", k)}"`, k)).join("")}
    <span class="g">Text</span>${[100, 125, 150].map((v) => b(v === ts, `data-ts="${v}"`, `${v}%`)).join("")}
    <span class="g"></span>${b(false, 'data-act="merge"', "+ merge")}${SCN === "fail" ? b(false, 'data-act="rerun"', "↻ force rerun") : ""}<span class="note">${esc(SCNS[SCN])}</span>`;
  ctl.querySelectorAll("[data-go]").forEach((e) => (e.onclick = () => (location.search = e.dataset.go)));
  ctl.querySelectorAll("[data-ts]").forEach((e) => (e.onclick = () => { document.documentElement.style.fontSize = e.dataset.ts === "100" ? "" : `${e.dataset.ts}%`; history.replaceState(null, "", addr("ts", e.dataset.ts)); }));
  ctl.querySelector('[data-act="merge"]').onclick = () => { arrive(); nextAt = now() + 25; };
  ctl.querySelector('[data-act="rerun"]')?.addEventListener("click", forceRerun);
}
setInterval(() => { const on = mine(), fs = rootFs(); if (ctl.hidden === on) { ctl.hidden = !on; if (on) renderCtl(); }
  if (fs !== F) { F = fs; if (on) { resize(); renderCtl(); } } }, 250);
if (P.has("merged")) { stack = [{ kind: "board" }, { kind: "fold", id: "apply-on-merge+graph-refresh+main-follow", dags: [NM.aom, NM.gr, NM.mf], crit: [], path: ["review", "done"] }];
  localStorage.setItem("fv.path", JSON.stringify(stack)); resize(); renderNav(); }
}
