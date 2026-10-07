// Design mockup of the Kanban's Waiting stacks, drawn when the address carries ?view=kanban.
// The board, columns, buckets and cards copy the page's Kanban (starpulse/web/src/Kanban.tsx and style.css) over board.js, a saved
// live Board. New here: a Waiting card whose dependency is Waiting in the same milestone stacks under it, the blocker on top with a
// count badge; hovering a stack unstacks it downward, shifting the cards below; a dependency on a Waiting task in another milestone
// shows as a link badge that opens the blocker's modal. Moves are simulated in the page against each task's saved move verdicts.
(() => {
  const params = new URLSearchParams(location.search);
  if (params.get("view") !== "kanban" || !window.BOARD) return;
  const B = window.BOARD, NOW = B.now;
  const COLUMNS = ["ready", "waiting", "in_progress", "review", "needs_attention", "done"];
  const SCENES = {
    board: "The whole board, stacks folded",
    unstack: "m-107 stack unstacked: a four-deep chain",
    multi: "m-100: a dependent with several Waiting blockers sits under the first",
    cross: "A Waiting dependency in another milestone: link badge",
    before: "Today's Kanban, no stacks, for comparison",
  };
  const scene = SCENES[params.get("s")] ? params.get("s") : "board";
  const SIZES = { 1: "100%", 1.25: "125%", 1.5: "150%" };
  let fs = SIZES[params.get("fs")] ? +params.get("fs") : 1;
  let stacking = scene !== "before";

  const tasks = B.tasks.map((t) => ({ ...t }));
  const byId = new Map(tasks.map((t) => [t.id, t]));
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const num = (id) => +(/(\d+)$/.exec(id)?.[1] ?? 0);
  const mnum = (m) => (m ? +(/^m-(\d+)/.exec(m)?.[1] ?? 0) : -1);
  const ago = (s) => { const m = Math.max(0, Math.round(s / 60)); return m < 1 ? "now" : m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`; };
  const short = (p) => p.replace(/^@agent-/, "").replace(/-(high|medium|low|max)$/, " $1");
  const hue = (s) => { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return `hsl(${h} 70% 65%)`; };

  let query = "", hovered = null, open = null, pinned = null, refusal = null;
  const folded = new Set(), hidden = new Set();

  // ---- the model: kanban.ts's layout and hold counts, plus the stacks this design adds
  const isOpen = (id) => byId.get(id) && byId.get(id).lane !== "done";
  const openDeps = (t) => t.dependencies.filter(isOpen);
  const matches = (t) => query.toLowerCase().split(/\s+/).filter(Boolean).every((w) => [t.id, t.title, ...t.labels].some((f) => f.toLowerCase().includes(w)));
  function edges() {
    const heldBy = new Map(), waitsOn = new Map();
    for (const t of tasks) {
      const deps = openDeps(t);
      if (t.lane === "done" || !deps.length) continue;
      waitsOn.set(t.id, deps);
      if (t.lane === "waiting") for (const d of deps) heldBy.set(d, [...(heldBy.get(d) ?? []), t.id]);
    }
    return { heldBy, waitsOn };
  }
  function reach(id, next) {
    const seen = new Set(), todo = [id];
    for (let at = todo.pop(); at !== undefined; at = todo.pop()) for (const n of next.get(at) ?? []) if (n !== id && !seen.has(n)) { seen.add(n); todo.push(n); }
    return seen;
  }
  function holders(holds) {
    return tasks.filter((t) => (holds.get(t.id) ?? 0) > 0 && !(t.lane === "waiting" && openDeps(t).length > 0))
      .map((task) => ({ task, holds: holds.get(task.id) }))
      .sort((a, b) => b.holds - a.holds || num(a.task.id) - num(b.task.id));
  }

  /** A Waiting bucket's cards as stacks: each top is a Waiting task with no Waiting dependency in the bucket; the rest sit under
   *  the stack of the blocker that unblocks first (lowest chain depth, then id), in unblock order. */
  function stacksOf(list) {
    const here = new Map(list.map((t) => [t.id, t]));
    const wdeps = (t) => t.dependencies.filter((d) => here.has(d) && d !== t.id);
    const depth = new Map(), root = new Map();
    const depthOf = (t, seen = new Set()) => {
      if (depth.has(t.id)) return depth.get(t.id);
      if (seen.has(t.id)) return 0; // a cycle stops here rather than recursing forever
      seen.add(t.id);
      const ds = wdeps(t), d = ds.length ? 1 + Math.max(...ds.map((x) => depthOf(here.get(x), seen))) : 0;
      depth.set(t.id, d);
      return d;
    };
    const firstBlocker = (t) => wdeps(t).map((x) => here.get(x)).sort((a, b) => depthOf(a) - depthOf(b) || num(a.id) - num(b.id))[0];
    const rootOf = (t, seen = new Set()) => {
      if (root.has(t.id)) return root.get(t.id);
      const f = seen.has(t.id) ? null : firstBlocker(t);
      seen.add(t.id);
      const r = f ? rootOf(f, seen) : t;
      root.set(t.id, r);
      return r;
    };
    const groups = new Map();
    for (const t of list) { const r = rootOf(t); groups.set(r.id, [...(groups.get(r.id) ?? []), t]); }
    return list.filter((t) => rootOf(t) === t).map((top) => ({
      top,
      members: groups.get(top.id).sort((a, b) => depthOf(a) - depthOf(b) || num(a.id) - num(b.id)),
      blockers: (t) => wdeps(t),
    }));
  }
  /** A Waiting card's Waiting dependencies in another milestone: they cannot stack, so each is a link badge. */
  const crossOf = (t) => t.lane !== "waiting" ? [] : t.dependencies.map((d) => byId.get(d)).filter((d) => d && d.lane === "waiting" && d.milestone !== t.milestone && !hidden.has(d.id));

  function layout() {
    const visible = tasks.filter((t) => COLUMNS.includes(t.lane) && !hidden.has(t.id) && matches(t));
    return COLUMNS.map((id) => {
      const here = visible.filter((t) => t.lane === id).sort((a, b) => b.entered - a.entered || num(b.id) - num(a.id));
      const keys = [...new Set(here.map((t) => t.milestone))].sort((a, b) => mnum(b) - mnum(a));
      return { id, name: B.names[id] ?? id, count: here.length, buckets: keys.map((m) => ({ milestone: m, tasks: here.filter((t) => t.milestone === m), folded: folded.has(m) })) };
    });
  }

  // ---- the page chrome: the Kanban's own styles, scaled by --fs as the Admin text size does
  const css = document.createElement("style");
  css.textContent = `
body.kanban { background: radial-gradient(ellipse at 40% 30%, #0b1224 0%, var(--bg0) 70%); }
body.kanban canvas, body.kanban #tip, body.kanban #panel, body.kanban #fanctl, body.kanban #clock, body.kanban #crumbs { visibility: hidden; }
body.kanban aside { font-size: calc(11px * var(--fs)); } body.kanban aside h3 { font-size: calc(10px * var(--fs)); }
body.kanban #feed { font-size: calc(10.5px * var(--fs)); }
#kb { position: fixed; z-index: 3; top: 0; bottom: 0; left: calc(var(--nav) + 20px); right: calc(var(--rail) + 20px); display: flex; flex-direction: column; font-size: calc(12px * var(--fs)); }
#kb header { display: flex; align-items: center; gap: 14px; height: 64px; flex: none; }
#kb header .title { font-size: calc(13px * var(--fs)); font-weight: 500; letter-spacing: .32em; text-transform: uppercase; opacity: .85; }
#kb header .count { font-size: calc(11px * var(--fs)); color: var(--muted); }
#kb .filters { position: relative; display: flex; gap: 8px; align-items: center; height: 34px; flex: none; margin-bottom: 12px; }
#kb .fchip { cursor: default; user-select: none; padding: 5px 10px; border-radius: 6px; border: 1px solid rgba(148,163,184,.18); font-size: calc(11.5px * var(--fs)); color: #94a3b8; display: flex; gap: 6px; align-items: center; white-space: nowrap; }
#kb .fchip b { font-weight: 400; color: var(--ink); }
#kb .fchip.set { cursor: pointer; border-color: rgba(167,139,250,.6); background: rgba(167,139,250,.10); }
#kb .shown { margin-left: auto; flex: none; white-space: nowrap; font-size: calc(11px * var(--fs)); color: var(--muted); }
#kb .fw { position: relative; flex: 0 1 260px; min-width: 120px; }
#kb .filters input { box-sizing: border-box; width: 100%; height: 28px; padding: 0 10px; border-radius: 6px; border: 1px solid rgba(148,163,184,.18); background: rgba(8,13,26,.7); color: var(--ink); font: inherit; font-size: calc(11.5px * var(--fs)); outline: none; }
#kb .filters input::placeholder { color: var(--muted); } #kb .filters input:focus { border-color: rgba(167,139,250,.7); }
#kb .clear { all: unset; cursor: pointer; padding: 5px 4px; font-size: calc(11.5px * var(--fs)); color: #c4b5fd; } #kb .clear:hover { color: var(--ink); text-decoration: underline; }
#kb #cols { flex: 1; min-height: 0; display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; padding-bottom: 16px; }
#kb .col { min-height: 0; display: flex; flex-direction: column; border-radius: 10px; background: rgba(148,163,184,.035); border: 1px solid rgba(148,163,184,.08); }
#kb .col.drop-ok { border-color: rgba(52,211,153,.55); background: rgba(52,211,153,.05); } #kb .col.drop-no { border-color: rgba(251,113,133,.45); }
#kb .col h2 { margin: 0; flex: none; display: flex; align-items: baseline; gap: 8px; padding: 12px 12px 10px; font-size: calc(11px * var(--fs)); font-weight: 500; letter-spacing: .2em; white-space: nowrap;
  text-transform: uppercase; color: #94a3b8; border-bottom: 1px solid rgba(148,163,184,.08); }
#kb .col h2 .nm { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
#kb .col h2 .c { flex: none; font-size: calc(11px * var(--fs)); letter-spacing: 0; color: var(--muted); font-variant-numeric: tabular-nums; }
#kb .col h2 .g { flex: none; width: 7px; height: 7px; border-radius: 50%; border: 1.5px solid currentColor; box-sizing: border-box; }
#kb .col h2 .cc { flex: none; margin-left: 6px; color: #fb923c; font-weight: 600; letter-spacing: 0; }
#kb .col .body { flex: 1; min-height: 0; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 7px; scrollbar-width: thin; scrollbar-color: rgba(148,163,184,.25) transparent; }
#kb .col .empty { margin: 18px auto; font-size: calc(11px * var(--fs)); color: #3f4c66; }
#kb .bucket { display: flex; flex-direction: column; gap: 7px; } #kb .bucket + .bucket { margin-top: 6px; }
#kb .bh { position: sticky; top: -8px; z-index: 4; display: flex; align-items: center; gap: 6px; margin: 0 -8px; padding: 6px 10px 5px; cursor: pointer; user-select: none;
  font-size: calc(10.5px * var(--fs)); color: #8b9bb8; background: rgba(9,14,26,.96); border-bottom: 1px solid rgba(148,163,184,.08); }
#kb .bh:hover { color: #cbd5e1; } #kb .bh .bn { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#kb .bh .c { color: var(--muted); font-variant-numeric: tabular-nums; } #kb .bh .tw { font-size: calc(9px * var(--fs)); transition: transform .15s; }
#kb .bucket.folded .tw { transform: rotate(-90deg); } #kb .bucket.folded > :not(.bh) { display: none; }
#kb .bh .hide { all: unset; display: none; cursor: pointer; padding: 0 5px; border-radius: 4px; color: var(--muted); font-size: calc(10.5px * var(--fs)); }
#kb .bh:hover .hide { display: inline; } #kb .bh .hide:hover { color: var(--ink); background: rgba(148,163,184,.15); } #kb .bh:hover .c { display: none; }
#kb .card { position: relative; flex: none; box-sizing: border-box; padding: 8px 9px 8px 10px; border-radius: 7px; background: rgb(12,19,34); border: 1px solid rgba(148,163,184,.13);
  line-height: 1.4; cursor: pointer; outline: none; touch-action: none; }
#kb .card:hover, #kb .card:focus-visible { border-color: rgba(148,163,184,.3); } #kb .card:focus-visible { box-shadow: 0 0 0 1px #a78bfa; }
#kb .card .top { display: flex; align-items: center; gap: 6px; font-size: calc(10.5px * var(--fs)); color: var(--muted); }
#kb .card .id { margin-right: auto; font-family: "JetBrains Mono", ui-monospace, monospace; color: #94a3b8; }
#kb .card .t { margin: 4px 0 6px; color: var(--ink); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
#kb .pr { display: flex; align-items: center; gap: 4px; font-family: "JetBrains Mono", ui-monospace, monospace; font-size: calc(10px * var(--fs)); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(148,163,184,.2); color: #94a3b8; }
#kb .pr i { width: 6px; height: 6px; border-radius: 50%; background: #475569; }
#kb .pr.pass i { background: #34d399; } #kb .pr.fail i { background: #fb7185; } #kb .pr.pending i { background: #fbbf24; } #kb .pr.merged i { background: #a78bfa; }
#kb .mach { display: flex; align-items: center; gap: 6px; font-size: calc(10.5px * var(--fs)); color: #8b95a8; margin-bottom: 6px; white-space: nowrap; }
#kb .mach b { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; font-weight: 400; color: #c4b5fd; } #kb .mach .s { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
#kb .mach .p { flex: none; position: relative; top: -1px; width: 6px; height: 6px; border-radius: 50%; background: #a78bfa; box-shadow: 0 0 6px #a78bfa; } #kb .mach .ago { flex: none; margin-left: auto; color: #475569; }
#kb .foot { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; font-size: calc(10px * var(--fs)); color: var(--muted); }
#kb .lab { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 0 5px; border-radius: 3px; background: rgba(148,163,184,.10); color: #94a3b8; line-height: 1.5; }
#kb .lab.nh { background: rgba(251,113,133,.14); color: #fda4af; } #kb .lab.sz { background: rgba(103,232,249,.10); color: #a5f3fc; }
#kb .who { margin-left: auto; display: flex; align-items: center; gap: 4px; white-space: nowrap; } #kb .who i { width: 6px; height: 6px; border-radius: 50%; }
#kb .dep { color: #fbbf24; } #kb .holds { color: #fb923c; font-weight: 600; }
#kb .col .heldby { flex: none; display: flex; align-items: center; gap: 5px; flex-wrap: wrap; padding: 6px 10px; font-size: calc(10.5px * var(--fs)); border-bottom: 1px solid rgba(251,146,60,.18); background: rgba(251,146,60,.05); }
#kb .heldby .k { color: var(--muted); margin-right: 2px; }
#kb .heldby .hb { all: unset; cursor: pointer; display: inline-flex; gap: 4px; padding: 1px 6px; border-radius: 3px; background: rgba(148,163,184,.10); color: #cbd5e1; font-family: "JetBrains Mono", ui-monospace, monospace; }
#kb .heldby .hb b { font-weight: 600; color: #fb923c; } #kb .heldby .hb.nh { background: rgba(251,113,133,.14); color: #fda4af; } #kb .heldby .hb:hover { outline: 1px solid rgba(251,146,60,.6); } #kb .heldby .more { color: var(--muted); }
#kb .card.chain-self { box-shadow: 0 0 0 1px #e2e8f0, 0 0 14px rgba(226,232,240,.18); }
#kb .card.chain-holds { box-shadow: 0 0 0 1px #fb923c, 0 0 12px rgba(251,146,60,.28); }
#kb .card.chain-waits { box-shadow: 0 0 0 1px #67e8f9, 0 0 12px rgba(103,232,249,.25); }
#kb .card.ghost { opacity: .35; } #kb .card.bad { border-color: rgba(251,113,133,.6); }
#kb .refusal { margin-top: 6px; padding: 6px 8px; border-radius: 5px; background: rgba(251,113,133,.08); border: 1px solid rgba(251,113,133,.3); font-size: calc(10.5px * var(--fs)); color: #fda4af; }
#kb .refusal .dismiss { all: unset; cursor: pointer; margin-left: 8px; color: var(--muted); text-decoration: underline; }
@keyframes kb-shake { 0%, 100% { transform: none; } 20%, 60% { transform: translateX(-4px); } 40%, 80% { transform: translateX(4px); } }
@keyframes kb-arrive { from { box-shadow: 0 0 0 1px #34d399, 0 0 18px rgba(52,211,153,.5); } to { box-shadow: none; } }
.kb-lift { position: fixed; z-index: 50; pointer-events: none; transform: rotate(1.5deg); box-shadow: 0 14px 30px rgba(0,0,0,.55); opacity: .95; }

/* NEW: a Waiting stack. Folded, the top card is whole and up to two card edges peek below it; unstacked, every member drops into
   the column's flow, pushing the cards below down, joined by the chain's spine. */
#kb .stack { position: relative; flex: none; isolation: isolate; transition: height .26s cubic-bezier(.3,.7,.2,1); }
#kb .stack > .card { position: absolute; left: 0; right: 0; top: 0; transition: transform .26s cubic-bezier(.3,.7,.2,1), opacity .2s, left .26s, right .26s; }
#kb .stack > .edge { position: absolute; height: 10px; border-radius: 0 0 7px 7px; background: rgb(17,25,43); border: 1px solid rgba(148,163,184,.30); border-top: 0; transition: opacity .18s; }
#kb .stack.open > .edge { opacity: 0; }
#kb .stack:not(.open) > .card.under { pointer-events: none; }
#kb .stack > .spine { position: absolute; left: 4px; width: 2px; top: 22px; border-radius: 1px; background: linear-gradient(rgba(251,146,60,.65), rgba(251,146,60,.15)); opacity: 0; transition: opacity .2s .08s; }
#kb .stack.open > .spine { opacity: 1; }
#kb .stack.open > .card.under { left: 12px; }
#kb .stack > .card.under .uw { display: none; margin: -2px 0 4px; font-size: calc(10px * var(--fs)); color: #fdba74; }
#kb .stack.open > .card.under .uw { display: block; }
#kb .sk { display: inline-flex; align-items: center; gap: 3px; padding: 0 6px; border-radius: 9px; line-height: 1.5; font-weight: 600; color: #fed7aa; background: rgba(251,146,60,.16); border: 1px solid rgba(251,146,60,.45); }
#kb .sk svg { width: 1em; height: 1em; }
#kb .xm { all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 3px; padding: 0 5px; border-radius: 3px; line-height: 1.5; color: #a5b4fc; background: rgba(129,140,248,.12); border: 1px dashed rgba(129,140,248,.5); white-space: nowrap; }
#kb .xm:hover, #kb .xm:focus-visible { color: #e0e7ff; border-style: solid; }
#kb .card.flash { animation: kb-arrive 1.6s ease-out; }

/* the task modal (simplified: the modal's own redesign is a separate design task) */
#kbm { position: fixed; inset: 0; z-index: 40; display: grid; place-items: center; background: rgba(2,4,10,.62); backdrop-filter: blur(2px); font-size: calc(12.5px * var(--fs)); }
#kbm .modal { position: relative; box-sizing: border-box; width: min(760px, calc(100vw - 40px)); max-height: 80vh; overflow: auto; padding: 22px 26px; border-radius: 12px; line-height: 1.6;
  background: rgba(12,19,34,.98); border: 1px solid rgba(148,163,184,.22); box-shadow: 0 30px 80px rgba(0,0,0,.6); }
#kbm h2 { margin: 0 0 4px; padding-right: 30px; font-size: calc(16px * var(--fs)); font-weight: 500; }
#kbm .k { color: var(--muted); font-size: calc(11px * var(--fs)); } #kbm .x { all: unset; position: absolute; top: 16px; right: 20px; cursor: pointer; color: var(--muted); font-size: calc(14px * var(--fs)); }
#kbm table { border-collapse: collapse; margin-top: 10px; width: 100%; } #kbm td { padding: 3px 12px 3px 0; vertical-align: top; } #kbm td:first-child { color: var(--muted); white-space: nowrap; width: 110px; }
#kbm a { color: #a78bfa; text-decoration: none; cursor: pointer; } #kbm a:hover { text-decoration: underline; }
#kbm .note { margin-top: 14px; color: var(--muted); font-size: calc(11px * var(--fs)); }

/* design review only: scene and text size, in the header so it covers no card */
#kbrev { margin-left: auto; display: flex; gap: 6px; align-items: center; font-size: 11px; color: var(--muted); }
#kbrev button { all: unset; white-space: nowrap; cursor: pointer; padding: 3px 8px; border-radius: 5px; border: 1px solid rgba(148,163,184,.25); }
#kbrev button.on { color: #fbbf24; border-color: #fbbf24; } #kbrev .sep { width: 1px; height: 16px; background: rgba(148,163,184,.25); margin: 0 4px; }
`;
  document.head.appendChild(css);
  document.body.classList.add("kanban");
  document.documentElement.style.setProperty("--fs", fs);

  const kb = document.createElement("main");
  kb.id = "kb";
  document.body.appendChild(kb);
  const modalHost = document.createElement("div");
  document.body.appendChild(modalHost);

  const STACK_ICON = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="2.5" y="2" width="11" height="7" rx="1.5"/><path d="M3.5 11.5h9M5 14h6"/></svg>';
  const checksClass = (p) => (p.merged ? "merged" : p.checks);

  function cardHtml(t, { holds, chain, under, stackCount, blockers }) {
    const cls = ["card", chain && `chain-${chain}`, under && "under", refusal?.id === t.id && "bad"].filter(Boolean).join(" ");
    const p = t.prs[0];
    const pr = p ? `<span class="pr ${checksClass(p)}" title="${p.merged ? "merged" : `checks ${p.checks}`}"><i></i>#${p.number}</span>` : "";
    const mach = t.live ? `<div class="mach"><span class="p"></span><b>${esc(t.live.machine)}</b><span class="s">· ${esc(t.live.state.replace(/_/g, " "))}</span><span class="ago">${ago(NOW - t.live.at)}</span></div>` : "";
    const labs = t.labels.map((l) => `<span title="${esc(l)}" class="lab${l === "needs-human" ? " nh" : /^size-/.test(l) ? " sz" : ""}">${esc(/^size-/.test(l) ? `${l.slice(5)}pt` : l)}</span>`).join("");
    const cross = stacking ? crossOf(t).map((d) => `<button class="xm" data-open="${esc(d.id)}" title="Waits on ${esc(d.id)} in ${esc(d.milestone || "No milestone")} (Waiting): open it">↗ ${esc(d.milestone || "no milestone")} · ${esc(d.id)}</button>`).join("") : "";
    const sk = stackCount ? `<span class="sk" title="${stackCount} Waiting task${stackCount === 1 ? "" : "s"} stacked under this one; hover to unstack">${STACK_ICON}${stackCount}</span>` : "";
    const od = openDeps(t).length;
    const uw = under && blockers?.length ? `<div class="uw">⧗ waits on ${blockers.map(esc).join(", ")}</div>` : "";
    const note = refusal?.id === t.id ? `<div class="refusal">Move to ${esc(B.names[refusal.to] ?? refusal.to)} refused · stayed in ${esc(B.names[t.lane])}<br>${esc(refusal.why)}<button class="dismiss" data-dismiss>dismiss</button></div>` : "";
    return `<div class="${cls}" role="button" tabindex="0" data-id="${esc(t.id)}">
      <div class="top"><span class="id">${esc(t.id)}</span>${pr}</div>${uw}
      <div class="t">${esc(t.title)}</div>${mach}
      <div class="foot">${labs}${sk}${holds ? `<span class="holds" title="holds ${holds} Waiting task${holds === 1 ? "" : "s"}">⛓${holds}</span>` : ""}${od ? `<span class="dep" title="open dependencies">⧗${od}</span>` : ""}${cross}
        ${t.assignee ? `<span class="who"><i style="background:${hue(t.assignee)}"></i>${esc(short(t.assignee))}</span>` : '<span class="who">unassigned</span>'}</div>${note}
    </div>`;
  }

  let holdsMap = new Map(), chainFn = null;
  function computeChain() {
    const e = edges();
    holdsMap = new Map([...e.heldBy.keys()].map((id) => [id, reach(id, e.heldBy).size]));
    chainFn = null;
    if (!hovered) return;
    const holds = reach(hovered, e.heldBy), waits = reach(hovered, e.waitsOn);
    if (!holds.size && !waits.size) return;
    chainFn = (id) => (id === hovered ? "self" : holds.has(id) ? "holds" : waits.has(id) ? "waits" : undefined);
  }

  function render() {
    const prevRects = rects();
    computeChain();
    const cols = layout();
    const shown = cols.reduce((n, c) => n + c.count, 0), done = cols.find((c) => c.id === "done").count;
    const total = tasks.filter((t) => COLUMNS.includes(t.lane)).length;
    const held = holders(holdsMap);
    const opts = { holds: 0 };
    const colHtml = cols.map((col) => {
      const inChain = chainFn ? col.buckets.flatMap((b) => b.tasks).filter((t) => ["holds", "waits"].includes(chainFn(t.id))).length : 0;
      const strip = col.id === "waiting" ? `<div class="heldby"><span class="k" title="The tasks every Waiting chain ends at">Held by</span>${held.slice(0, 3).map(({ task, holds }) => `<button class="hb${task.labels.includes("needs-human") ? " nh" : ""}" data-open="${esc(task.id)}" data-hover="${esc(task.id)}" title="${esc(task.title)} · holds ${holds}">${esc(task.id)}<b>⛓${holds}</b></button>`).join("")}${held.length > 3 ? `<span class="more">+${held.length - 3} more</span>` : ""}</div>` : "";
      const body = col.buckets.length ? col.buckets.map((b) => {
        let inner;
        if (col.id === "waiting" && stacking) inner = stacksOf(b.tasks).map((s) => stackHtml(s)).join("");
        else inner = b.tasks.map((t) => cardHtml(t, { ...opts, holds: holdsMap.get(t.id), chain: chainFn?.(t.id) })).join("");
        return `<div class="bucket${b.folded ? " folded" : ""}" data-m="${esc(b.milestone)}"><div class="bh" data-fold="${esc(b.milestone)}" title="${esc(b.milestone || "No milestone")}"><span class="tw">▾</span><span class="bn">${esc(b.milestone || "No milestone")}</span><span class="c">${b.tasks.length}</span><button class="hide" data-hidem="${esc(b.milestone)}">hide</button></div>${inner}</div>`;
      }).join("") : '<div class="empty">no tasks</div>';
      return `<section class="col" data-lane="${col.id}"><h2><span class="g"></span><span class="nm" title="${esc(col.name)}">${esc(col.name)}</span><span class="c">${col.count}</span>${inChain ? `<span class="cc">⛓${inChain}</span>` : ""}</h2>${strip}<div class="body">${body}</div></section>`;
    }).join("");
    const scroll = [...kb.querySelectorAll(".col .body")].map((b) => b.scrollTop);
    const hadFocus = document.activeElement?.id === "kbq";
    kb.innerHTML = `<header><span class="title">Kanban</span><span class="count">${shown - done} open · ${done} done</span>
      <div id="kbrev" title="Design review controls, not part of the page"><span>scene</span>${Object.entries(SCENES).map(([k, v]) => `<button data-scene="${k}" class="${k === scene ? "on" : ""}" title="${esc(v)}">${k}</button>`).join("")}<span class="sep"></span><span>text</span>${Object.entries(SIZES).map(([k, v]) => `<button data-fs="${k}" class="${+k === fs ? "on" : ""}">${v}</button>`).join("")}</div></header>
      <div class="filters"><div class="fw"><input id="kbq" type="text" value="${esc(query)}" placeholder="filter by id, title or label…" autocomplete="off" spellcheck="false"></div>
        <span class="fchip">Assignee <b>any</b></span><span class="fchip">Milestone <b>any</b></span>${query ? '<button class="clear" data-clear>clear</button>' : ""}${hidden.size ? `<span class="fchip set" data-showall>${hidden.size} hidden · show</span>` : ""}
        <span class="shown">${shown} of ${total} tasks</span></div>
      <div id="cols">${colHtml}</div>`;
    kb.querySelectorAll(".col .body").forEach((b, i) => (b.scrollTop = scroll[i] ?? 0));
    if (hadFocus) { const q = kb.querySelector("#kbq"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
    kb.querySelectorAll(".stack").forEach((s) => settle(s, s.dataset.top === pinned || s.dataset.top === openStack, false));
    flip(prevRects);
  }

  function stackHtml(s) {
    const n = s.members.length - 1;
    const cards = s.members.map((t, i) => cardHtml(t, { holds: holdsMap.get(t.id), chain: chainFn?.(t.id), under: i > 0, stackCount: i === 0 ? n : 0, blockers: s.blockers(t) })).join("");
    if (!n) return cards;
    const edges = Array.from({ length: Math.min(2, n) }, (_, i) => `<div class="edge" style="left:${(i + 1) * 5}px;right:${(i + 1) * 5}px;z-index:${-1 - i}"></div>`).join("");
    return `<div class="stack" data-top="${esc(s.top.id)}" data-n="${n}">${edges}<div class="spine"></div>${cards}</div>`;
  }

  /** Lay a stack's cards out folded (layered under the top, edges peeking) or unstacked (in flow, the column below pushed down). */
  function settle(el, unstacked, animate = true) {
    const cards = [...el.querySelectorAll(":scope > .card")];
    if (!animate) el.style.transition = "none", cards.forEach((c) => (c.style.transition = "none"));
    el.classList.toggle("open", unstacked);
    const hs = cards.map((c) => c.offsetHeight), gap = 7, peek = Math.min(2, cards.length - 1) * 5;
    let y = 0;
    cards.forEach((c, i) => {
      c.style.zIndex = String(cards.length - i);
      if (unstacked) { c.style.transform = `translateY(${y}px)`; c.style.opacity = "1"; y += hs[i] + gap; }
      else { c.style.transform = i === 0 ? "none" : `translateY(${hs[0] - hs[i] + Math.min(i, 2) * 5}px) scale(${1 - Math.min(i, 2) * 0.03})`; c.style.opacity = i === 0 ? "1" : "0"; }
    });
    el.querySelectorAll(":scope > .edge").forEach((e, i) => (e.style.top = `${hs[0] - 6 + i * 5}px`));
    const spine = el.querySelector(".spine");
    el.style.height = `${unstacked ? y - gap : hs[0] + peek}px`;
    if (spine) spine.style.height = `${Math.max(0, y - gap - 30)}px`;
    if (!animate) { void el.offsetHeight; el.style.transition = ""; cards.forEach((c) => (c.style.transition = "")); }
  }

  // ---- FLIP: cards that move between renders (a move, a fold, a filter) glide to their new place
  function rects() { return new Map([...kb.querySelectorAll(".card")].map((c) => [c.dataset.id, c.getBoundingClientRect()])); }
  function flip(prev) {
    if (!prev.size) return;
    for (const c of kb.querySelectorAll(".card")) {
      const a = prev.get(c.dataset.id), b = c.getBoundingClientRect();
      if (!a || !b.width || (Math.abs(a.left - b.left) < 1 && Math.abs(a.top - b.top) < 1)) continue;
      if (c.parentElement.classList.contains("stack")) continue; // a stack lays its own cards out
      c.animate([{ transform: `translate(${a.left - b.left}px, ${a.top - b.top}px)` }, { transform: "none" }], { duration: 320, easing: "cubic-bezier(.3,.7,.2,1)" });
    }
  }

  // ---- hover: unstack after a short intent delay; fold back once the pointer leaves the unstacked cards
  let openStack = null, intent = null;
  kb.addEventListener("pointerover", (e) => {
    const card = e.target.closest(".card");
    const id = card?.dataset.id ?? e.target.closest("[data-hover]")?.dataset.hover ?? null;
    if (id !== hovered && !drag) { hovered = id; paintChain(); }
    const st = e.target.closest(".stack");
    if (st && st.dataset.top !== openStack && !drag) {
      clearTimeout(intent);
      intent = setTimeout(() => { if (openStack && openStack !== st.dataset.top) fold(openStack); openStack = st.dataset.top; settle(st, true); }, 140);
    }
  });
  kb.addEventListener("pointerout", (e) => {
    const st = e.target.closest(".stack");
    if (st && !st.contains(e.relatedTarget)) { clearTimeout(intent); if (openStack === st.dataset.top) { openStack = null; if (pinned !== st.dataset.top) settle(st, false); } }
    if (!kb.contains(e.relatedTarget) && hovered) { hovered = null; paintChain(); }
  });
  kb.addEventListener("focusin", (e) => { const st = e.target.closest(".stack"); if (st) settle(st, true); });
  kb.addEventListener("focusout", (e) => { const st = e.target.closest(".stack"); if (st && !st.contains(e.relatedTarget) && openStack !== st.dataset.top && pinned !== st.dataset.top) settle(st, false); });
  function fold(top) { const st = kb.querySelector(`.stack[data-top="${CSS.escape(top)}"]`); if (st && pinned !== top) settle(st, false); }
  function paintChain() {
    computeChain();
    for (const c of kb.querySelectorAll(".card")) { c.classList.remove("chain-self", "chain-holds", "chain-waits"); const k = chainFn?.(c.dataset.id); if (k) c.classList.add(`chain-${k}`); }
    for (const col of kb.querySelectorAll(".col")) {
      const n = chainFn ? [...col.querySelectorAll(".card")].filter((c) => ["holds", "waits"].includes(chainFn(c.dataset.id))).length : 0;
      let cc = col.querySelector("h2 .cc");
      if (!n) { cc?.remove(); continue; }
      if (!cc) { cc = document.createElement("span"); cc.className = "cc"; col.querySelector("h2").appendChild(cc); }
      cc.textContent = `⛓${n}`;
    }
  }

  // ---- clicks: open a card's modal, a link badge opens its blocker, fold and hide buckets, review controls
  kb.addEventListener("click", (e) => {
    const t = e.target;
    if (t.closest("[data-dismiss]")) { refusal = null; render(); return; }
    const o = t.closest("[data-open]"); if (o) { e.stopPropagation(); openModal(o.dataset.open); return; }
    const hm = t.closest("[data-hidem]"); if (hm) { e.stopPropagation(); for (const x of tasks) if (x.milestone === hm.dataset.hidem) hidden.add(x.id); render(); return; }
    const f = t.closest("[data-fold]"); if (f) { const m = f.dataset.fold; folded.has(m) ? folded.delete(m) : folded.add(m); render(); return; }
    if (t.closest("[data-clear]")) { query = ""; render(); return; }
    if (t.closest("[data-showall]")) { hidden.clear(); render(); return; }
    const sc = t.closest("[data-scene]"); if (sc) { params.set("s", sc.dataset.scene); location.search = params; return; }
    const z = t.closest("[data-fs]"); if (z) { fs = +z.dataset.fs; params.set("fs", z.dataset.fs); history.replaceState(null, "", `?${params}`); document.documentElement.style.setProperty("--fs", fs); render(); return; }
    const c = t.closest(".card"); if (c && !justDragged) openModal(c.dataset.id);
  });
  kb.addEventListener("keydown", (e) => {
    e.stopPropagation(); // the Star Map's own keys (Backspace, 0) stay out of the Kanban
    if (e.key === "Enter" && e.target.classList.contains("card")) openModal(e.target.dataset.id);
  });
  kb.addEventListener("input", (e) => { if (e.target.id === "kbq") { query = e.target.value; render(); } });

  function openModal(id) {
    const t = byId.get(id); if (!t) return;
    open = id;
    const deps = t.dependencies.map((d) => byId.get(d)).filter(Boolean);
    const stack = t.lane === "waiting" ? stacksOf(tasks.filter((x) => x.lane === "waiting" && x.milestone === t.milestone && !hidden.has(x.id))).find((s) => s.members.includes(t)) : null;
    const link = (x) => `<a data-open="${esc(x.id)}">${esc(x.id)}</a> <span class="k">${esc(B.names[x.lane] ?? x.lane)}${x.milestone !== t.milestone ? ` · ${esc(x.milestone || "no milestone")}` : ""}</span>`;
    modalHost.innerHTML = `<div id="kbm"><div class="modal" role="dialog" aria-label="${esc(t.id)}"><button class="x" data-close aria-label="Close">✕</button>
      <div class="k">${esc(t.id)} · ${esc(B.names[t.lane] ?? t.lane)}</div><h2>${esc(t.title)}</h2>
      <table><tr><td>Milestone</td><td>${esc(t.milestone || "none")}</td></tr><tr><td>Assignee</td><td>${esc(t.assignee || "unassigned")}</td></tr>
      <tr><td>Labels</td><td>${t.labels.map(esc).join(", ") || "none"}</td></tr>
      <tr><td>Dependencies</td><td>${deps.length ? deps.map(link).join("<br>") : "none"}</td></tr>
      ${stack && stack.members.length > 1 ? `<tr><td>Waiting stack</td><td>${stack.members.map((x, i) => `${i ? "↳ " : "▣ "}${x === t ? `<b>${esc(x.id)}</b>` : `<a data-open="${esc(x.id)}">${esc(x.id)}</a>`}`).join("<br>")}</td></tr>` : ""}</table>
      <div class="note">Mockup: the full task view is unchanged by this design; see the task-modal design task.</div></div></div>`;
  }
  modalHost.addEventListener("click", (e) => {
    const o = e.target.closest("[data-open]"); if (o) { openModal(o.dataset.open); return; }
    if (e.target.closest("[data-close]") || e.target.id === "kbm") closeModal();
  });
  function closeModal() { open = null; modalHost.innerHTML = ""; }
  addEventListener("keydown", (e) => { if (e.key === "Escape" && open) { e.stopImmediatePropagation(); closeModal(); } }, true);

  // ---- drag a card to another column, checked against the task's saved move verdicts as the server would
  let drag = null, justDragged = false;
  kb.addEventListener("pointerdown", (e) => {
    const c = e.target.closest(".card");
    if (!c || e.button !== 0 || e.target.closest("button,a")) return;
    drag = { id: c.dataset.id, x: e.clientX, y: e.clientY, el: c, lift: null };
  });
  addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (!drag.lift && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 6) return;
    if (!drag.lift) {
      const r = drag.el.getBoundingClientRect();
      drag.lift = drag.el.cloneNode(true); drag.lift.classList.add("kb-lift"); drag.lift.style.width = `${r.width}px`; drag.lift.style.transform = "rotate(1.5deg)";
      drag.dx = e.clientX - r.left; drag.dy = e.clientY - r.top; document.body.appendChild(drag.lift); drag.el.classList.add("ghost");
    }
    drag.lift.style.left = `${e.clientX - drag.dx}px`; drag.lift.style.top = `${e.clientY - drag.dy}px`;
    const col = document.elementsFromPoint(e.clientX, e.clientY).find((x) => x.classList?.contains("col"));
    kb.querySelectorAll(".col").forEach((x) => x.classList.remove("drop-ok", "drop-no"));
    const t = byId.get(drag.id);
    if (col && col.dataset.lane !== t.lane) col.classList.add(t.moves[col.dataset.lane]?.allowed ? "drop-ok" : "drop-no");
  });
  addEventListener("pointerup", (e) => {
    if (!drag) return;
    const d = drag; drag = null;
    if (!d.lift) return;
    justDragged = true; setTimeout(() => (justDragged = false), 0);
    d.lift.remove(); d.el.classList.remove("ghost");
    kb.querySelectorAll(".col").forEach((x) => x.classList.remove("drop-ok", "drop-no"));
    const col = document.elementsFromPoint(e.clientX, e.clientY).find((x) => x.classList?.contains("col"));
    const t = byId.get(d.id);
    if (!col || col.dataset.lane === t.lane) return;
    const to = col.dataset.lane, v = t.moves[to];
    if (v?.allowed) { refusal = null; t.lane = to; t.entered = NOW; render(); const n = kb.querySelector(`.card[data-id="${CSS.escape(t.id)}"]`); n?.classList.add("flash"); n?.scrollIntoView({ block: "nearest" }); }
    else { refusal = { id: t.id, to, why: v ? `guarded${v.skill ? ` · satisfied by ${v.skill}` : ""}` : `no transition from ${B.names[t.lane]} to ${B.names[to]}` }; render(); kb.querySelector(`.card[data-id="${CSS.escape(t.id)}"]`)?.animate([{ transform: "translateX(-4px)" }, { transform: "translateX(4px)" }, { transform: "none" }], { duration: 300, iterations: 2 }); }
  });

  // ---- the scene the address names
  render();
  const bucket = (m) => kb.querySelector(`.col[data-lane="waiting"] .bucket[data-m="${CSS.escape(m)}"]`);
  const reveal = (el) => { if (!el) return; const body = el.closest(".body"); body.scrollTop += el.getBoundingClientRect().top - body.getBoundingClientRect().top - 40; };
  if (scene === "unstack") {
    const b = bucket("m-107"), st = b && [...b.querySelectorAll(".stack")].sort((x, y) => y.dataset.n - x.dataset.n)[0];
    if (st) { pinned = st.dataset.top; settle(st, true, false); reveal(b); }
  } else if (scene === "multi") {
    const b = bucket("m-100"); reveal(b);
    const st = b?.querySelector(".stack"); if (st) { pinned = st.dataset.top; settle(st, true, false); }
  } else if (scene === "cross") {
    const x = kb.querySelector(".col[data-lane='waiting'] .xm"); const b = x?.closest(".bucket"); reveal(b);
    const st = x?.closest(".stack"); if (st) { pinned = st.dataset.top; settle(st, true, false); }
    x?.animate([{ boxShadow: "0 0 0 0 rgba(129,140,248,.8)" }, { boxShadow: "0 0 0 8px rgba(129,140,248,0)" }], { duration: 1200, iterations: 3 });
  }
  // a pinned scene stack folds again once the operator hovers and leaves it, like any other
  kb.addEventListener("pointerout", (e) => { const st = e.target.closest(".stack"); if (st && pinned === st.dataset.top && !st.contains(e.relatedTarget)) { pinned = null; settle(st, false); } });
})();
