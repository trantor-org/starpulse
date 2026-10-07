// Layers discovery mockup layer (D5): the navigator's Layers tree goes; a breadcrumb on the canvas takes over the way
// back out, and the panel space shows one of three Star Map variants or, on the Kanban, one of four filter panels.
// Injected over a scrubbed capture of the live page; it only adds elements and styles, so React keeps owning the page.
// Seeded, synthetic data (the snapshot has no such fields yet): park reasons and one failing pull request.
(() => {
  const F = window.__FLOW_FIXTURE__;
  const MAP = ["attention", "flow", "sessions"], KAN = ["lenses", "milestones", "facets", "sessions"], DRILL = ["board", "state", "machine"], SIZES = [100, 125, 150];
  const qs = new URLSearchParams(location.search);
  const kanban = qs.get("view") === "kanban";
  const p = MAP.includes(qs.get("p")) ? qs.get("p") : "attention";
  const k = KAN.includes(qs.get("k")) ? qs.get("k") : "lenses";
  const d = DRILL.includes(qs.get("d")) ? qs.get("d") : "board";
  const fs = SIZES.includes(+qs.get("fs")) ? +qs.get("fs") : null;
  const STALE_H = +qs.get("stale") || 4;
  const store = (key, v) => { try { localStorage.setItem(key, v); } catch {} };
  const read = (key) => { try { return JSON.parse(localStorage.getItem(key) || "null"); } catch { return null; } };
  if (fs) store("fv.admin.prefs", JSON.stringify({ ...(read("fv.admin.prefs") || {}), scale: fs }));
  store("fv.nav.folded", "0");
  store("fv.kanban.prefs", JSON.stringify({ query: "", assignee: null, milestone: null, folded: [], hiddenMilestones: [], hiddenTasks: [] }));
  const root = document.documentElement;
  if (qs.get("dags") === "0") root.classList.add("ly-nodags");
  if (qs.get("chrome") === "0") root.classList.add("ly-nochrome");

  // ---- data: read once from the fixture, before the app's deferred module reads it ----
  const now = F.now;
  const board = F.flows.find((f) => f.name === "board").agents;
  const ip = F.flows.find((f) => f.name === "in-progress").agents;
  const states = F.flows.find((f) => f.name === "board").machine.states;
  const byId = Object.fromEntries(board.map((a) => [a.id, a]));
  const ipOf = Object.fromEntries(ip.map((a) => [a.id, a]));
  const openPr = (id) => (F.pulls[id] || []).find((x) => !x.merged);
  // seeded: one claimed task's open pull request fails its checks, so the Red CI group and its card have a row
  const red = board.find((a) => a.state === "in_progress" && openPr(a.id));
  if (red) openPr(red.id).checks = "fail";
  const REASONS = ["decide: drop the v1 ingest route or keep it behind a flag", "merge conflict: pick which side of the cache config wins",
    "approve the render: the legend clips at 125% text", "grant the deploy step its DEMO_TOKEN secret", "pick a retention window, 7 or 30 days"];
  const reason = {};
  board.filter((a) => a.state === "needs_attention").forEach((a, i) => (reason[a.id] = REASONS[i % REASONS.length]));
  const quiet = (id) => (ipOf[id] ? now - ipOf[id].active : 0);
  const ago = (s) => (s < 3600 ? `${Math.max(1, Math.round(s / 60))}m` : s < 86400 ? `${Math.floor(s / 3600)}h ${String(Math.round((s % 3600) / 60)).padStart(2, "0")}m` : `${Math.round(s / 86400)}d`);
  const claimed = board.filter((a) => a.state === "in_progress").sort((a, b) => quiet(a.id) - quiet(b.id));
  const ATTN = [
    { key: "na", title: "Needs you", tone: "#fb923c", rows: board.filter((a) => a.state === "needs_attention").map((a) => ({ id: a.id, title: a.title, meta: ago(now - a.entered), why: reason[a.id] })) },
    { key: "merge", title: "Ready to merge", tone: "#34d399", rows: board.filter((a) => a.state === "review" && openPr(a.id)?.checks === "pass" && !openPr(a.id).threads).map((a) => ({ id: a.id, title: a.title, meta: `#${openPr(a.id).number}` })) },
    { key: "red", title: "Red CI", tone: "#fb7185", rows: board.filter((a) => openPr(a.id)?.checks === "fail").map((a) => ({ id: a.id, title: a.title, meta: `#${openPr(a.id).number}` })) },
    { key: "stale", title: `Quiet over ${STALE_H}h`, tone: "#fbbf24", rows: claimed.filter((a) => quiet(a.id) > STALE_H * 3600).map((a) => ({ id: a.id, title: a.title, meta: ago(quiet(a.id)) })).reverse() },
  ];
  // the Phoenix day an epoch falls on; America/Phoenix keeps UTC-7 all year
  const day = (t) => Math.floor((t - 7 * 3600) / 86400), today = day(now);
  const hist = Object.values(F.history).flat();
  const settledIn = (s) => Object.values(F.settled).filter((x) => x.state === s);
  const FLOW = states.map((s) => {
    const here = board.filter((a) => a.state === s.id), fin = s.final ? settledIn(s.id) : [];
    // a final state's arrivals are its settled tasks; New's are the tasks created that day
    const at = s.final ? fin.map((x) => x.at) : s.initial ? [...board, ...Object.values(F.settled)].map((x) => x.created).filter(Boolean) : hist.filter((e) => e.to === s.id).map((e) => e.at);
    const ins = Array.from({ length: 7 }, (_, i) => at.filter((t) => day(t) === today - 6 + i).length);
    const ages = here.map((a) => now - a.entered).sort((x, y) => x - y);
    const oldest = here.reduce((o, a) => (!o || a.entered < o.entered ? a : o), null);
    return { id: s.id, name: s.name, count: here.length + fin.length, ins, out: hist.filter((e) => e.from === s.id && day(e.at) === today).length,
      med: ages.length ? ages[Math.floor(ages.length / 2)] : null, oldest: s.final ? null : oldest };
  });
  const sub = (id) => (ipOf[id]?.state || "claimed").replace(/_/g, " ");
  // the count beside a state is the one its sun carries, read from the hidden tree the canvas shares
  const countOf = (name) => (layerNodes().find((b) => b.querySelector(".t")?.textContent === name)?.querySelector(".n")?.textContent || "").replace(/[▾▸]/g, "");
  const tier = (m) => (/deep/.test(m) ? "#c4b5fd" : /standard/.test(m) ? "#67e8f9" : "#fde68a");
  const holders = new Set(board.filter((a) => a.state === "waiting").flatMap((a) => a.dependencies || []));
  const lab = (a, re) => (a.labels.find((l) => re.test(l)) || "").replace(re, "");
  const prState = (a) => { const o = openPr(a.id); if (o) return o.checks === "fail" ? "failing" : o.checks === "pending" ? "pending" : "passing"; return (F.pulls[a.id] || []).length ? "merged" : "no PR"; };
  const FACETS = [
    { key: "pr", title: "Pull request", of: prState, values: ["failing", "pending", "passing", "merged", "no PR"] },
    { key: "deps", title: "Dependencies", of: (a) => (a.state === "waiting" && (a.dependencies || []).length ? "blocked" : holders.has(a.id) ? "holds others" : "free"), values: ["blocked", "holds others", "free"] },
    { key: "claim", title: "Session", of: (a) => (a.state === "in_progress" ? "claimed" : "unclaimed"), values: ["claimed", "unclaimed"] },
    { key: "kind", title: "Kind", of: (a) => lab(a, /^kind-/) || "none", values: ["decide", "execute", "diagnose", "mechanical", "none"] },
    { key: "size", title: "Size", of: (a) => lab(a, /^size-/) || "none", values: ["1", "2", "3", "5", "8", "none"] },
  ];
  const MS = Object.entries(board.reduce((m, a) => { if (a.milestone && a.state !== "archived") { (m[a.milestone] ||= { done: 0, total: 0 }).total++; if (a.state === "done") m[a.milestone].done++; } return m; }, {}))
    .filter(([, v]) => v.done < v.total).sort((x, y) => y[1].total - x[1].total);

  const css = `
  #nav section.layers, #nav section.note { display: none !important; }
  html.ly-nodags #nav section.away:has(#cons) { display: none !important; }
  /* the panel scrolls in whatever height DAGs and Queues leave it; a fade at the foot says there is more */
  #nav section.ly-panel { flex: 1; min-height: 0; overflow: auto; padding-bottom: 18px; -webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 22px), transparent); mask-image: linear-gradient(to bottom, #000 calc(100% - 22px), transparent); }
  .ly-h { display: flex; align-items: baseline; gap: 6px; }
  .ly-h h3 { margin: 0; }
  .ly-h .ly-clear { all: unset; cursor: pointer; margin-left: auto; font-size: calc(10px * var(--fs)); color: var(--muted); letter-spacing: .04em; }
  .ly-h .ly-clear:hover, .ly-h .ly-clear:focus-visible { color: var(--ink); }
  .ly-grp { margin: 12px 0 2px; display: flex; align-items: center; gap: 7px; font-size: calc(10.5px * var(--fs)); letter-spacing: .12em; text-transform: uppercase; color: #94a3b8; }
  .ly-grp:first-child { margin-top: 4px; }
  .ly-grp i { width: 6px; height: 6px; border-radius: 50%; flex: none; }
  .ly-grp .n { margin-left: auto; letter-spacing: 0; color: var(--muted); }
  .ly-row { all: unset; box-sizing: border-box; width: 100%; cursor: pointer; display: grid; grid-template-columns: auto 1fr auto; column-gap: 8px; align-items: baseline;
    padding: 4px 6px; margin: 0 -6px; width: calc(100% + 12px); border-radius: 5px; font-size: calc(12px * var(--fs)); line-height: 1.35; color: #cbd5e1; }
  .ly-row:hover, .ly-row:focus-visible { background: rgba(148,163,184,.08); }
  .ly-row.on { background: rgba(167,139,250,.16); box-shadow: inset 2px 0 0 #a78bfa; }
  .ly-row .id { font-family: "JetBrains Mono", ui-monospace, Menlo, monospace; font-size: calc(11px * var(--fs)); color: var(--ink); }
  .ly-row .t { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #94a3b8; }
  .ly-row .m { font-size: calc(11px * var(--fs)); color: var(--muted); font-variant-numeric: tabular-nums; }
  .ly-row .why { grid-column: 1 / -1; font-size: calc(11px * var(--fs)); color: #fdba74; opacity: .9; white-space: normal; }
  .ly-row .sub2 { grid-column: 1 / -1; display: flex; flex-wrap: wrap; align-items: center; column-gap: 8px; row-gap: 1px; font-size: calc(10.5px * var(--fs)); color: var(--muted); white-space: nowrap; }
  .ly-row .sub2 b { font-weight: 400; color: #94a3b8; }
  .ly-row .sub2 svg { flex: none; }
  .ly-row .dot { width: 6px; height: 6px; border-radius: 50%; align-self: center; }
  .ly-row.stale .m { color: #fbbf24; }
  .ly-none { font-size: calc(11px * var(--fs)); color: var(--muted); padding: 2px 0 4px; }
  .ly-bar { grid-column: 1 / -1; height: 3px; border-radius: 2px; background: rgba(148,163,184,.14); overflow: hidden; margin-top: 3px; }
  .ly-bar > i { display: block; height: 100%; background: #a78bfa; }
  .ly-chips { display: flex; flex-wrap: wrap; gap: 4px; margin: 2px 0 4px; }
  .ly-chip { all: unset; cursor: pointer; box-sizing: border-box; padding: 2px 7px; border-radius: 10px; border: 1px solid rgba(148,163,184,.22); font-size: calc(11px * var(--fs)); color: #cbd5e1; white-space: nowrap; }
  .ly-chip .n { color: var(--muted); margin-left: 4px; font-variant-numeric: tabular-nums; }
  .ly-chip:hover, .ly-chip:focus-visible { border-color: rgba(167,139,250,.6); }
  .ly-chip.on { border-color: #a78bfa; background: rgba(167,139,250,.18); color: #fff; }
  .ly-chip.off { opacity: .4; cursor: default; }
  .ly-note { font-size: calc(10.5px * var(--fs)); color: var(--muted); margin-top: 8px; line-height: 1.5; }
  /* Kanban: a lens dims the cards outside it, a filter hides them, a session row lights its card */
  #kb .card.ly-dim { opacity: .16; transition: opacity .2s; }
  #kb .card.ly-hide, #kb .bucket.ly-hide { display: none !important; }
  #kb .heldby.ly-dimmed { opacity: .3; }
  #kb .card.ly-lit { box-shadow: 0 0 0 1px #a78bfa, 0 0 14px rgba(167,139,250,.55) !important; }
  /* the canvas breadcrumb: where the map is drilled, each level above a click away */
  #ly-crumb { position: fixed; z-index: 4; top: 16px; display: flex; align-items: center; gap: 2px; padding: 4px 6px; border-radius: 7px;
    background: rgba(5,7,13,.55); backdrop-filter: blur(4px); font-size: calc(12px * var(--fs)); color: var(--muted); white-space: nowrap; max-width: 46vw; overflow: hidden; }
  #ly-crumb button { all: unset; cursor: pointer; padding: 2px 6px; border-radius: 4px; color: #94a3b8; }
  #ly-crumb button:hover, #ly-crumb button:focus-visible { color: var(--ink); background: rgba(148,163,184,.12); }
  #ly-crumb .here { padding: 2px 6px; color: var(--ink); }
  #ly-crumb .sep { opacity: .5; }
  #ly-crumb .n { margin-left: 5px; color: var(--muted); font-variant-numeric: tabular-nums; }
  body.kanban #ly-crumb { display: none; }
  /* the mockup's own switcher, outside the page's design */
  #ly-sw { position: fixed; z-index: 50; bottom: 10px; left: 50%; transform: translateX(-50%); display: flex; gap: 10px; align-items: center; padding: 6px 10px; border-radius: 8px;
    background: rgba(15,20,34,.94); border: 1px dashed rgba(167,139,250,.45); font: 11px Inter, system-ui, sans-serif; color: #94a3b8; white-space: nowrap; }
  #ly-sw b { font-weight: 500; color: #c4b5fd; letter-spacing: .08em; cursor: pointer; }
  #ly-sw .grp { display: flex; gap: 4px; align-items: center; }
  #ly-sw button { all: unset; cursor: pointer; padding: 2px 7px; border-radius: 4px; border: 1px solid rgba(148,163,184,.22); color: #cbd5e1; }
  #ly-sw button.on { border-color: #a78bfa; background: rgba(167,139,250,.18); color: #fff; }
  #ly-sw.min .grp { display: none; }
  html.ly-nochrome #ly-sw { display: none; }
  `;
  const el = (tag, attrs = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [a, v] of Object.entries(attrs)) a.startsWith("on") ? (e[a] = v) : v != null && e.setAttribute(a, v);
    for (const c of kids.flat(Infinity)) if (c != null) e.append(c);
    return e;
  };
  const esc = (s) => document.createTextNode(String(s));

  // ---- the app's own navigation, driven through the hidden Layers tree and the search box ----
  const layerNodes = () => [...document.querySelectorAll("#layers .node")];
  const clickLayer = (name) => { const n = layerNodes().find((b) => b.querySelector(".t")?.textContent === name); if (n) n.click(); return !!n; };
  const setValue = (input, v) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, v);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  };
  // Enter on a search takes its first hit, as the page does; the query is cleared again so the search box is left as it was
  const pinTask = (id) => {
    const q = document.getElementById("q");
    if (!q) return;
    setValue(q, id);
    setTimeout(() => { q.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); setTimeout(() => setValue(q, ""), 30); }, 30);
  };
  const stateName = (id) => states.find((s) => s.id === id)?.name;

  // ---- Star Map panels ----
  const rowFor = (r, extra = {}) => el("button", { class: "ly-row" + (extra.cls ? " " + extra.cls : ""), title: r.title, onclick: extra.onclick || (() => pinTask(r.id)) },
    extra.dot ? el("i", { class: "dot", style: `background:${extra.dot}` }) : el("span", { class: "id" }, esc(r.id)),
    extra.dot ? el("span", { class: "t" }, el("span", { class: "id" }, esc(r.id)), esc("  " + (extra.text ?? r.title))) : el("span", { class: "t" }, esc(r.title)),
    el("span", { class: "m" }, esc(r.meta)), r.why ? el("span", { class: "why" }, esc(r.why)) : null);
  const spark = (ins) => {
    const max = Math.max(1, ...ins), w = 4, g = 2;
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("width", 7 * (w + g)); s.setAttribute("height", 12); s.setAttribute("aria-hidden", "true");
    ins.forEach((v, i) => { const r = document.createElementNS(s.namespaceURI, "rect"); const h = Math.max(1, Math.round((v / max) * 12));
      Object.entries({ x: i * (w + g), y: 12 - h, width: w, height: h, rx: 1, fill: i === 6 ? "#a78bfa" : "rgba(148,163,184,.45)" }).forEach(([a, v2]) => r.setAttribute(a, v2)); s.append(r); });
    return s;
  };
  const mapPanel = {
    attention: () => [el("div", { class: "ly-h" }, el("h3", {}, esc("Attention"))),
      ATTN.flatMap((g) => [el("div", { class: "ly-grp" }, el("i", { style: `background:${g.tone}` }), esc(g.title), el("span", { class: "n" }, esc(g.rows.length))),
        g.rows.length ? g.rows.map((r) => rowFor(r)) : el("div", { class: "ly-none" }, esc("clear"))])],
    flow: () => [el("div", { class: "ly-h" }, el("h3", {}, esc("State flow")), el("span", { class: "ly-clear", style: "cursor:default" }, esc("7 days in"))),
      FLOW.map((s) => el("button", { class: "ly-row", title: `Open ${s.name}`, onclick: () => clickLayer(s.name) },
        el("span", { class: "id", style: "font-family:inherit;font-size:inherit" }, esc(s.name)), el("span"), el("span", { class: "m" }, esc(countOf(s.name) || s.count)),
        el("span", { class: "sub2" }, spark(s.ins), el("span", {}, el("b", {}, esc(`+${s.ins[6]}`)), esc(` −${s.out} today`)),
          s.med != null ? el("span", {}, esc(`med ${ago(s.med)}`)) : null, s.oldest ? el("span", { title: s.oldest.title }, esc(`oldest ${ago(now - s.oldest.entered)}`)) : null)))],
    sessions: () => [el("div", { class: "ly-h" }, el("h3", {}, esc("Sessions")), el("span", { class: "ly-clear", style: "cursor:default" }, esc(`${claimed.length} claimed`))),
      claimed.map((a) => rowFor({ id: a.id, title: a.title, meta: ago(quiet(a.id)) }, { dot: tier(a.model), text: sub(a.id), cls: quiet(a.id) > STALE_H * 3600 ? "stale" : "" }))],
  };

  // ---- Kanban panels: each sets the predicate the cards are dimmed, hidden or lit by ----
  let pick = { kind: null }; // { kind: "dim"|"hide"|"lit", ids:Set, label }
  const facetOn = {}; // facet key -> Set of values
  let mile = null, lens = null, lit = null;
  const applyCards = () => {
    document.querySelectorAll("#kb .card[data-id]").forEach((c) => {
      const id = c.dataset.id, inSet = pick.ids ? pick.ids.has(id) : true;
      c.classList.toggle("ly-dim", pick.kind === "dim" && !inSet);
      c.classList.toggle("ly-hide", pick.kind === "hide" && !inSet);
      c.classList.toggle("ly-lit", pick.kind === "lit" && inSet);
    });
    // a filter also folds away the buckets it empties and says how many cards it left, as the toolbar's own filters do
    document.querySelectorAll("#kb .bucket").forEach((bk) => bk.classList.toggle("ly-hide", pick.kind === "hide" && !bk.querySelector(".card[data-id]:not(.ly-hide)")));
    document.querySelectorAll("#kb .heldby").forEach((h) => h.classList.toggle("ly-dimmed", !!pick.kind && pick.kind !== "lit"));
    const patch = (node, want) => {
      if (!node) return;
      if (want != null && !node.dataset.lyOrig) node.dataset.lyOrig = node.textContent;
      if (want != null && node.textContent !== want) node.textContent = want;
      if (want == null && node.dataset.lyOrig) { node.textContent = node.dataset.lyOrig; delete node.dataset.lyOrig; }
    };
    const hiding = pick.kind === "hide", shown = document.querySelector("#kb .shown");
    const total = (shown?.dataset.lyOrig || shown?.textContent || "").match(/of (\d+) tasks/)?.[1];
    patch(shown, hiding && total ? `${document.querySelectorAll("#kb .card[data-id]:not(.ly-hide)").length} of ${total} tasks` : null);
    document.querySelectorAll("#kb section.col").forEach((col) => patch(col.querySelector("h2 .c"), hiding ? String(col.querySelectorAll(".card[data-id]:not(.ly-hide)").length) : null));
  };
  const clearBtn = () => (pick.kind ? el("button", { class: "ly-clear", onclick: () => { pick = { kind: null }; mile = lens = lit = null; Object.keys(facetOn).forEach((key) => delete facetOn[key]); render(); } }, esc("clear ✕")) : null);
  const kanPanel = {
    lenses: () => [el("div", { class: "ly-h" }, el("h3", {}, esc("Attention")), clearBtn()),
      ATTN.flatMap((g) => [el("button", { class: "ly-row" + (lens === g.key ? " on" : ""), onclick: () => { lens = lens === g.key ? null : g.key; pick = lens ? { kind: "dim", ids: new Set(g.rows.map((r) => r.id)) } : { kind: null }; render(); } },
        el("i", { class: "dot", style: `background:${g.tone}` }), el("span", { class: "t", style: "color:#cbd5e1" }, esc(g.title)), el("span", { class: "m" }, esc(g.rows.length)),
        lens === g.key && g.rows.length ? el("span", { class: "sub2", style: "white-space:normal;display:block" }, esc(g.rows.map((r) => r.id).join(" · "))) : null)]),
      el("div", { class: "ly-note" }, esc("A lens dims every card outside it; click again to lift it."))],
    milestones: () => [el("div", { class: "ly-h" }, el("h3", {}, esc("Milestones")), clearBtn()),
      MS.map(([m, v]) => el("button", { class: "ly-row" + (mile === m ? " on" : ""), onclick: () => { mile = mile === m ? null : m; pick = mile ? { kind: "hide", ids: new Set(board.filter((a) => a.milestone === m).map((a) => a.id)) } : { kind: null }; render(); } },
        el("span", { class: "id" }, esc(m)), el("span"), el("span", { class: "m" }, esc(`${v.done}/${v.total}`)), el("span", { class: "ly-bar" }, el("i", { style: `width:${Math.round((v.done / v.total) * 100)}%` }))))],
    facets: () => [el("div", { class: "ly-h" }, el("h3", {}, esc("Facets")), clearBtn()),
      FACETS.flatMap((f) => [el("div", { class: "ly-grp" }, esc(f.title)), el("div", { class: "ly-chips" }, f.values.map((v) => {
        const n = board.filter((a) => f.of(a) === v).length, on = facetOn[f.key]?.has(v);
        return el("button", { class: "ly-chip" + (on ? " on" : "") + (n ? "" : " off"), onclick: n ? () => {
          const s = (facetOn[f.key] ||= new Set()); s.has(v) ? s.delete(v) : s.add(v); if (!s.size) delete facetOn[f.key];
          const keys = Object.keys(facetOn);
          pick = keys.length ? { kind: "hide", ids: new Set(board.filter((a) => keys.every((key) => facetOn[key].has(FACETS.find((x) => x.key === key).of(a)))).map((a) => a.id)) } : { kind: null };
          render(); } : null }, esc(v), el("span", { class: "n" }, esc(n)));
      }))]),
      el("div", { class: "ly-grp" }, esc("Priority")), el("div", { class: "ly-none" }, esc("not in the snapshot yet: a backend field"))],
    sessions: () => [el("div", { class: "ly-h" }, el("h3", {}, esc("Sessions")), clearBtn()),
      claimed.map((a) => rowFor({ id: a.id, title: a.title, meta: ago(quiet(a.id)) }, { dot: tier(a.model), text: sub(a.id), cls: (quiet(a.id) > STALE_H * 3600 ? "stale" : "") + (lit === a.id ? " on" : ""),
        onclick: () => { lit = lit === a.id ? null : a.id; pick = lit ? { kind: "lit", ids: new Set([lit]) } : { kind: null }; render();
          if (lit) document.querySelector(`#kb .card[data-id="${lit}"]`)?.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" }); } }))],
  };

  // ---- mounting: the panel takes Layers' slot (Star Map) or the note's slot (Kanban), and stays there through React renders ----
  const panel = el("section", { class: "away ly-panel" });
  const render = () => {
    // Rebuilding the panel would drop keyboard focus to <body>; put it back on the same control.
    // Match the label exactly, then without its counts (they change with the selection), then by position.
    const ctrls = () => [...panel.querySelectorAll("button")], line = (b) => b.innerText.split("\n")[0].trim(), bare = (t) => t.replace(/\d+/g, "");
    const at = ctrls().indexOf(document.activeElement), was = at >= 0 ? line(document.activeElement) : null;
    panel.replaceChildren(...(kanban ? kanPanel[k]() : mapPanel[p]()).flat(Infinity).filter(Boolean)); applyCards();
    if (at >= 0) (ctrls().find((b) => line(b) === was) || ctrls().find((b) => bare(line(b)) === bare(was)) || ctrls()[at] || ctrls().pop())?.focus();
  };
  const place = () => {
    const nav = document.getElementById("nav");
    if (!nav) return;
    const anchor = nav.querySelector(kanban ? "section.note" : "section.layers");
    if (anchor && panel.previousElementSibling !== anchor) anchor.after(panel);
  };
  const crumb = el("nav", { id: "ly-crumb", "aria-label": "Where the map is drilled" });
  let last = "";
  const drawCrumb = () => {
    const on = layerNodes().filter((n) => n.classList.contains("on"));
    const names = on.map((n) => n.querySelector(".t").textContent), key = names.join("/");
    const nav = document.getElementById("nav");
    if (nav) crumb.style.left = `${nav.getBoundingClientRect().right + 20}px`;
    if (key === last) return;
    last = key;
    const hereCount = on.at(-1)?.querySelector(".n")?.textContent.replace(/[▾▸]/g, "") || "";
    crumb.replaceChildren(...names.flatMap((name, i) => {
      const lastOne = i === names.length - 1;
      return [i ? el("span", { class: "sep" }, esc("›")) : null,
        lastOne ? el("span", { class: "here", "aria-current": "location" }, esc(name), el("span", { class: "n" }, esc(hereCount))) : el("button", { onclick: () => clickLayer(name) }, esc(name))];
    }).filter(Boolean));
  };

  // ---- the switcher: every choice is a link, so each state can be sent ----
  const go = (patch) => { const n = new URLSearchParams(location.search); for (const [a, v] of Object.entries(patch)) v == null ? n.delete(a) : n.set(a, v); location.search = n.toString(); };
  const btn = (text, on, patch) => el("button", { class: on ? "on" : null, onclick: () => go(patch) }, esc(text));
  const sw = el("div", { id: "ly-sw" }, el("b", { title: "Minimise", onclick: () => sw.classList.toggle("min") }, esc("D5 MOCKUP")),
    el("span", { class: "grp" }, btn("Star Map", !kanban, { view: null }), btn("Kanban", kanban, { view: "kanban" })),
    kanban ? el("span", { class: "grp" }, esc("panel"), KAN.map((x) => btn(x, x === k, { k: x })))
      : el("span", { class: "grp" }, esc("panel"), MAP.map((x) => btn(x, x === p, { p: x })), esc(" drill"), DRILL.map((x) => btn(x === "state" ? "In Progress" : x === "machine" ? "authoring-skills" : "Board", x === d, { d: x }))),
    el("span", { class: "grp" }, esc("DAGs"), btn("in panel", qs.get("dags") !== "0", { dags: null }), btn("moved out", qs.get("dags") === "0", { dags: "0" })),
    el("span", { class: "grp" }, esc("text"), SIZES.map((x) => btn(`${x}%`, (fs || 100) === x, { fs: x }))));

  const start = () => {
    document.head.append(el("style", {}, css));
    document.body.append(crumb, sw);
    render();
    new MutationObserver(() => { place(); applyCards(); }).observe(document.getElementById("root"), { childList: true, subtree: true, characterData: true });
    place();
    setInterval(drawCrumb, 200);
    // a linked drill opens through the hidden tree, as a click on a sun would
    if (!kanban && d !== "board") {
      const t0 = Date.now();
      const step = () => {
        if (!clickLayer("In Progress")) return Date.now() - t0 < 4000 && setTimeout(step, 100);
        if (d === "machine") { const t1 = Date.now(); const m = () => clickLayer("authoring-skills") || (Date.now() - t1 < 3000 && setTimeout(m, 100)); setTimeout(m, 150); }
      };
      setTimeout(step, 300);
    }
  };
  const wait = () => (document.getElementById("nav") ? start() : setTimeout(wait, 50));
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", wait); else wait();
})();
