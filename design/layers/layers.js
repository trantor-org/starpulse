// Layers discovery mockup layer (D5): the navigator's Layers tree goes; a breadcrumb on the canvas takes over the way
// back out. The Star Map shows one of three minimal attention variants; the Kanban gets a milestone outline.
// Injected over a scrubbed capture of the live page; it only adds elements and styles, so React keeps owning the page.
// Seeded, synthetic data (the snapshot has no such fields yet): park reasons and one failing pull request.
(() => {
  const F = window.__FLOW_FIXTURE__;
  const MAP = ["none", "line", "crumb"], DRILL = ["board", "state", "machine"], SIZES = [100, 125, 150];
  const qs = new URLSearchParams(location.search);
  const kanban = qs.get("view") === "kanban";
  const p = MAP.includes(qs.get("p")) ? qs.get("p") : "line";
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
  const ipOf = Object.fromEntries(ip.map((a) => [a.id, a]));
  const openPr = (id) => (F.pulls[id] || []).find((x) => !x.merged);
  // seeded: one claimed task's open pull request fails its checks, so Red CI has a row
  const red = board.find((a) => a.state === "in_progress" && openPr(a.id));
  if (red) openPr(red.id).checks = "fail";
  const REASONS = ["decide: drop the v1 ingest route or keep it behind a flag", "merge conflict: pick which side of the cache config wins",
    "approve the render: the legend clips at 125% text", "grant the deploy step its DEMO_TOKEN secret", "pick a retention window, 7 or 30 days"];
  const reason = {};
  board.filter((a) => a.state === "needs_attention").forEach((a, i) => (reason[a.id] = REASONS[i % REASONS.length]));
  const quiet = (id) => (ipOf[id] ? now - ipOf[id].active : 0);
  const hrs = (s) => (s < 86400 ? `${Math.floor(s / 3600)}h` : `${Math.round(s / 86400)}d`);
  // what needs the operator, most urgent first; a task shows once, under its first reason, as one muted word
  const seen = new Set();
  const ATTN = [
    ...board.filter((a) => a.state === "needs_attention").map((a) => ({ a, word: "needs you", why: reason[a.id] })),
    ...board.filter((a) => openPr(a.id)?.checks === "fail").map((a) => ({ a, word: "red CI", why: `#${openPr(a.id).number} checks fail` })),
    ...board.filter((a) => a.state === "review" && openPr(a.id)?.checks === "pass" && !openPr(a.id).threads).map((a) => ({ a, word: "merge", why: `#${openPr(a.id).number} is green` })),
    ...board.filter((a) => a.state === "in_progress" && quiet(a.id) > STALE_H * 3600).sort((x, y) => quiet(y.id) - quiet(x.id))
      .map((a) => ({ a, word: `quiet ${hrs(quiet(a.id))}`, why: `no session activity for ${hrs(quiet(a.id))}` })),
  ].filter((r) => !seen.has(r.a.id) && seen.add(r.a.id));
  const MS = Object.entries(board.reduce((m, a) => { if (a.milestone && a.state !== "archived") { (m[a.milestone] ||= { done: 0, total: 0 }).total++; if (a.state === "done") m[a.milestone].done++; } return m; }, {}))
    .filter(([, v]) => v.done < v.total).sort((x, y) => y[1].total - x[1].total);

  const thin = "scrollbar-width: thin; scrollbar-color: rgba(148,163,184,.25) transparent;";
  const css = `
  #nav section.layers, #nav section.note { display: none !important; }
  html.ly-nodags #nav section.away:has(#cons) { display: none !important; }
  /* every scrolling box wears the Kanban columns' thin, quiet scrollbar */
  #root, #root *, #ly-pop { ${thin} }
  #nav section.ly-panel { flex: 1; min-height: 0; overflow: auto; }
  #nav section.ly-panel:empty { display: none; }
  .ly-tog { all: unset; cursor: pointer; display: flex; width: 100%; align-items: baseline; }
  .ly-tog .n { margin-left: auto; letter-spacing: 0; font-variant-numeric: tabular-nums; }
  .ly-tog:hover, .ly-tog:focus-visible { color: var(--ink); }
  .ly-row { all: unset; box-sizing: border-box; cursor: pointer; display: grid; grid-template-columns: 1fr auto; column-gap: 10px; align-items: baseline;
    padding: 3px 6px; margin: 0 -6px; width: calc(100% + 12px); border-radius: 4px; font-size: calc(12px * var(--fs)); line-height: 1.4; }
  .ly-row:hover, .ly-row:focus-visible { background: rgba(148,163,184,.08); }
  .ly-row.on { background: rgba(167,139,250,.14); }
  .ly-row .id { font-family: "JetBrains Mono", ui-monospace, Menlo, monospace; font-size: calc(11.5px * var(--fs)); color: var(--ink); }
  .ly-row .w { font-size: calc(11px * var(--fs)); color: var(--muted); font-variant-numeric: tabular-nums; }
  .ly-bar { grid-column: 1 / -1; height: 2px; border-radius: 1px; background: rgba(148,163,184,.12); overflow: hidden; margin-top: 3px; }
  .ly-bar > i { display: block; height: 100%; background: rgba(167,139,250,.7); }
  .ly-clear { all: unset; cursor: pointer; margin-left: auto; letter-spacing: .04em; text-transform: none; }
  .ly-clear:hover, .ly-clear:focus-visible { color: var(--ink); }
  #kb .card.ly-hide, #kb .bucket.ly-hide { display: none !important; }
  #kb .heldby.ly-dimmed { opacity: .3; }
  /* the canvas breadcrumb: plain text where the map is drilled, each level above a click away */
  #ly-crumb { position: fixed; z-index: 4; top: 18px; display: flex; align-items: baseline; gap: 4px; font-size: calc(12px * var(--fs)); color: var(--muted); white-space: nowrap; }
  #ly-crumb button { all: unset; cursor: pointer; color: var(--muted); }
  #ly-crumb button:hover, #ly-crumb button:focus-visible { color: var(--ink); }
  #ly-crumb .here { color: var(--ink); }
  #ly-crumb .sep { opacity: .5; }
  #ly-crumb .ly-att { margin-left: 14px; }
  body.kanban #ly-crumb, body.kanban #ly-pop { display: none; }
  #ly-pop { position: fixed; z-index: 5; min-width: 200px; max-height: 50vh; overflow: auto; padding: 6px 12px; border-radius: 6px;
    background: rgba(8,11,19,.96); border: 1px solid rgba(148,163,184,.12); }
  #ly-pop[hidden] { display: none; }
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

  // ---- Star Map: attention as bare ids with one word each; nothing at all when nothing needs you ----
  const attnRows = (then) => ATTN.map((r) => el("button", { class: "ly-row", title: `${r.a.title}\n${r.why}`, onclick: () => { then?.(); pinTask(r.a.id); } },
    el("span", { class: "id" }, esc(r.a.id)), el("span", { class: "w" }, esc(r.word))));
  let open = qs.has("open") ? qs.get("open") === "1" : read("ly.attn.open") ?? false; // ?open=1 links the expanded list
  const toggle = () => { open = !open; store("ly.attn.open", JSON.stringify(open)); render(); };
  const mapPanel = {
    none: () => [],
    line: () => (ATTN.length ? [el("h3", {}, el("button", { class: "ly-tog", "aria-expanded": String(open), onclick: toggle },
      esc(`${open ? "▾" : "▸"} Attention`), el("span", { class: "n" }, esc(ATTN.length)))), open ? attnRows() : null] : []),
    crumb: () => [],
  };

  // ---- Kanban: the milestone outline filters the board to one milestone ----
  let mile = null;
  const ids = () => (mile ? new Set(board.filter((a) => a.milestone === mile).map((a) => a.id)) : null);
  const applyCards = () => {
    const keep = ids();
    document.querySelectorAll("#kb .card[data-id]").forEach((c) => c.classList.toggle("ly-hide", !!keep && !keep.has(c.dataset.id)));
    // a filter also folds away the buckets it empties and recounts, as the toolbar's own filters do
    document.querySelectorAll("#kb .bucket").forEach((bk) => bk.classList.toggle("ly-hide", !!keep && !bk.querySelector(".card[data-id]:not(.ly-hide)")));
    document.querySelectorAll("#kb .heldby").forEach((h) => h.classList.toggle("ly-dimmed", !!keep));
    const patch = (node, want) => {
      if (!node) return;
      if (want != null && !node.dataset.lyOrig) node.dataset.lyOrig = node.textContent;
      if (want != null && node.textContent !== want) node.textContent = want;
      if (want == null && node.dataset.lyOrig) { node.textContent = node.dataset.lyOrig; delete node.dataset.lyOrig; }
    };
    const shown = document.querySelector("#kb .shown");
    const total = (shown?.dataset.lyOrig || shown?.textContent || "").match(/of (\d+) tasks/)?.[1];
    patch(shown, keep && total ? `${document.querySelectorAll("#kb .card[data-id]:not(.ly-hide)").length} of ${total} tasks` : null);
    document.querySelectorAll("#kb section.col").forEach((col) => patch(col.querySelector("h2 .c"), keep ? String(col.querySelectorAll(".card[data-id]:not(.ly-hide)").length) : null));
  };
  const kanPanel = () => [el("h3", { class: "ly-tog", style: "cursor:default" }, esc("Milestones"), mile ? el("button", { class: "ly-clear", onclick: () => { mile = null; render(); } }, esc("clear ✕")) : null),
    MS.map(([m, v]) => el("button", { class: "ly-row" + (mile === m ? " on" : ""), onclick: () => { mile = mile === m ? null : m; render(); } },
      el("span", { class: "id" }, esc(m)), el("span", { class: "w" }, esc(`${v.done}/${v.total}`)), el("span", { class: "ly-bar" }, el("i", { style: `width:${Math.round((v.done / v.total) * 100)}%` }))))];

  // ---- mounting: the panel takes Layers' slot (Star Map) or the note's slot (Kanban), and stays there through React renders ----
  const panel = el("section", { class: "away ly-panel" });
  const pop = el("div", { id: "ly-pop", hidden: "", role: "dialog", "aria-label": "Needs attention" });
  const render = () => {
    // Rebuilding would drop keyboard focus to <body>; put it back on the same control.
    // Match the label exactly, then without its counts (they change with the selection), then by position.
    const ctrls = () => [...panel.querySelectorAll("button"), ...pop.querySelectorAll("button")], line = (b) => b.innerText.split("\n")[0].trim(), bare = (t) => t.replace(/[\d▾▸]+/g, "");
    const at = ctrls().indexOf(document.activeElement), was = at >= 0 ? line(document.activeElement) : null;
    panel.replaceChildren(...(kanban ? kanPanel() : mapPanel[p]()).flat(Infinity).filter(Boolean)); applyCards();
    if (at >= 0) (ctrls().find((b) => line(b) === was) || ctrls().find((b) => bare(line(b)) === bare(was)) || ctrls()[at] || ctrls().pop())?.focus();
  };
  const place = () => {
    const nav = document.getElementById("nav");
    if (!nav) return;
    const anchor = nav.querySelector(kanban ? "section.note" : "section.layers");
    if (anchor && panel.previousElementSibling !== anchor) anchor.after(panel);
  };
  const crumb = el("nav", { id: "ly-crumb", "aria-label": "Where the map is drilled" });
  // crumb variant: the attention count trails the breadcrumb and opens a small list under it
  const att = p === "crumb" && ATTN.length ? el("button", { class: "ly-att", "aria-haspopup": "dialog", "aria-expanded": "false", onclick: () => showPop(pop.hidden) }, esc(`${ATTN.length} need you`)) : null;
  const showPop = (show) => {
    pop.hidden = !show; att?.setAttribute("aria-expanded", String(show));
    if (!show) return;
    pop.replaceChildren(...attnRows(() => showPop(false)));
    const r = att.getBoundingClientRect();
    Object.assign(pop.style, { left: `${r.left - 6}px`, top: `${r.bottom + 8}px` });
    pop.querySelector("button")?.focus();
  };
  addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) { showPop(false); att.focus(); } });
  addEventListener("pointerdown", (e) => { if (!pop.hidden && !pop.contains(e.target) && e.target !== att) showPop(false); });
  let last = "";
  const drawCrumb = () => {
    const on = layerNodes().filter((n) => n.classList.contains("on"));
    const names = on.map((n) => n.querySelector(".t").textContent), key = names.join("/");
    const nav = document.getElementById("nav");
    if (nav) crumb.style.left = `${nav.getBoundingClientRect().right + 24}px`;
    if (key === last) return;
    last = key;
    crumb.replaceChildren(...names.flatMap((name, i) => [i ? el("span", { class: "sep" }, esc("›")) : null,
      i === names.length - 1 ? el("span", { class: "here", "aria-current": "location" }, esc(name)) : el("button", { onclick: () => clickLayer(name) }, esc(name))]).concat(att).filter(Boolean));
  };

  // ---- the switcher: every choice is a link, so each state can be sent ----
  const go = (patch) => { const n = new URLSearchParams(location.search); for (const [a, v] of Object.entries(patch)) v == null ? n.delete(a) : n.set(a, v); location.search = n.toString(); };
  const btn = (text, on, patch) => el("button", { class: on ? "on" : null, onclick: () => go(patch) }, esc(text));
  const sw = el("div", { id: "ly-sw" }, el("b", { title: "Minimise", onclick: () => sw.classList.toggle("min") }, esc("D5 MOCKUP")),
    el("span", { class: "grp" }, btn("Star Map", !kanban, { view: null }), btn("Kanban", kanban, { view: "kanban" })),
    kanban ? null : el("span", { class: "grp" }, esc("attention"), MAP.map((x) => btn(x, x === p, { p: x })), esc(" drill"), DRILL.map((x) => btn(x === "state" ? "In Progress" : x === "machine" ? "authoring-skills" : "Board", x === d, { d: x }))),
    el("span", { class: "grp" }, esc("DAGs"), btn("in panel", qs.get("dags") !== "0", { dags: null }), btn("moved out", qs.get("dags") === "0", { dags: "0" })),
    el("span", { class: "grp" }, esc("text"), SIZES.map((x) => btn(`${x}%`, (fs || 100) === x, { fs: x }))));

  const start = () => {
    document.head.append(el("style", {}, css));
    document.body.append(crumb, pop, sw);
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
