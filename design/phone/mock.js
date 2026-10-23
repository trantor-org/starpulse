// Design mockup layer (the page at phone width), never part of the page. The page above is a scrubbed capture of the real
// StarPulse page, built from a source copy (phone-src.patch) that adds, inside the page's own 900 px collapse: a phone navigator (a
// view bar along the bottom edge, or a corner button, each opening the real navigator as a sheet), the Kanban one lane at a time (a
// lane strip, or stacked lane headers), the DAGs' rows on two lines and the Admin's rows stacked. Each sits behind a switch on <html>
// that this layer sets, so the same build draws today's page too. Without ?frame, on a wide window, this layer draws the review frame:
// today's page beside the proposal, each in an iframe at 390x844. On a phone-width window it shows the proposal itself, with a chip
// to change the variant. It runs before the page's module.
//   ?view=constellation|kanban|dags|admin   the view shown        ?fs=100|125|150   the Admin text size
//   ?nav=bar|drawer|overlay   the phone navigator                  ?kb=tabs|stack    the Kanban's lanes
//   ?lane=in_progress|ready|...   the Kanban lane open at the start
//   ?s=sheet|task|dag   a starting state: the navigator sheet open, a task open (Kanban), a DAG open (DAGs)
//   ?frame=1&phone=on|current   one page alone, as each iframe loads it (current: today's page, no switch set)
(() => {
  const q = new URLSearchParams(location.search);
  const pick = (k, vals) => (vals.includes(q.get(k)) ? q.get(k) : vals[0]);
  const VIEWS = ["kanban", "dags", "admin", "constellation"], NAVS = ["bar", "drawer", "overlay"], KBS = ["tabs", "stack"], STATES = ["none", "sheet", "task", "dag"];
  const NAMES = { kanban: "Kanban", dags: "DAGs", admin: "Admin", constellation: "Star Map", bar: "bottom bar", drawer: "drawer", overlay: "full overlay", tabs: "lane strip", stack: "stacked lanes",
    100: "100%", 125: "125%", 150: "150%", none: "the view", sheet: "navigator open", task: "task open", dag: "DAG open", on: "proposed", current: "today" };
  const fs = pick("fs", ["100", "125", "150"]), nav = pick("nav", NAVS), kb = pick("kb", KBS), view = pick("view", VIEWS), phone = pick("phone", ["on", "current"]), s = pick("s", STATES);
  try {
    const k = "fv.admin.prefs", p = JSON.parse(localStorage.getItem(k) || "{}");
    p.scale = Number(fs);
    localStorage.setItem(k, JSON.stringify(p));
  } catch { /* storage off: the page keeps 100% */ }
  // a task opens from the Kanban and a DAG from the DAGs, so those states bring their view
  const go = (k, v) => { q.set(k, v); if (k === "s" && v === "task") q.set("view", "kanban"); if (k === "s" && v === "dag") q.set("view", "dags"); location.search = q.toString(); };
  const seg = (label, key, vals, cur) => `<span class="lb">${label}</span><span class="seg">${
    vals.map((v) => `<button data-k="${key}" data-v="${v}" class="${v === cur ? "on" : ""}">${NAMES[v] ?? v}</button>`).join("")}</span>`;
  const SEG = `
    .mk .lb { color: var(--ink-3); font-size: 11.5px; }
    .mk .seg { display: inline-flex; flex-wrap: wrap; border-radius: 5px; border: 1px solid color-mix(in srgb, var(--slate) 25%, transparent); overflow: hidden; }
    .mk .seg button { all: unset; padding: 3px 11px; font-size: 11.5px; color: var(--ink-3); }
    .mk .seg button + button { border-left: 1px solid color-mix(in srgb, var(--slate) 18%, transparent); }
    .mk .seg button.on { background: color-mix(in srgb, var(--agent) 22%, transparent); color: var(--ink); }
    .mk .seg button:hover, .mk .seg button:focus-visible { background: color-mix(in srgb, var(--agent) 12%, transparent); }`;
  const style = (text) => { const st = document.createElement("style"); st.textContent = text; document.head.append(st); };

  const small = matchMedia("(max-width: 900px)").matches;
  if (q.has("frame") || small) {
    const H = document.documentElement;
    if (phone === "on") { H.dataset.phone = ""; H.dataset.pnav = nav; H.dataset.pkb = kb; }
    if (q.get("lane")) window.__PHONE_LANE__ = q.get("lane");
    if (!q.has("view")) { q.set("view", view); history.replaceState(null, "", `${location.pathname}?${q}`); }
    // a starting state is reached the way a finger reaches it: the page's own control is clicked once it has drawn
    const first = { sheet: nav === "bar" ? "#pnav .more" : "#pnavb", task: "#kb .col.on .card", dag: "#dg .trow" }[s];
    if (first && phone === "on") {
      let tries = 0;
      const t = setInterval(() => {
        const el = [...document.querySelectorAll(first)].find((e) => e.getClientRects().length);
        if (el) { clearInterval(t); el.click(); } else if (++tries > 100) clearInterval(t);
      }, 100);
    }
    // on a real phone there is no review frame: a chip opens the variants
    if (!q.has("frame")) addEventListener("DOMContentLoaded", () => {
      style(`${SEG}
        #mkchip { all: unset; position: fixed; z-index: 90; top: 6px; right: 6px; padding: 2px 8px; border-radius: 999px; font: 10px Inter, system-ui, sans-serif; letter-spacing: .14em;
          color: var(--run-text); background: color-mix(in srgb, var(--glass) 90%, transparent); border: 1px solid color-mix(in srgb, var(--run) 45%, transparent); }
        #mkmenu { position: fixed; z-index: 91; top: 30px; right: 6px; left: 6px; display: none; flex-direction: column; gap: 6px; padding: 12px; border-radius: 10px; font-family: Inter, system-ui, sans-serif;
          background: var(--pop); border: 1px solid color-mix(in srgb, var(--slate) 30%, transparent); box-shadow: 0 12px 30px color-mix(in srgb, var(--shadow) 50%, transparent); }
        #mkmenu.open { display: flex; }
        #mkmenu p { margin: 0 0 4px; font-size: 11.5px; line-height: 1.5; color: var(--muted); }`);
      const chip = document.createElement("button"), menu = document.createElement("div");
      chip.id = "mkchip"; chip.textContent = "MOCKUP"; chip.setAttribute("aria-label", "Mockup variants");
      menu.id = "mkmenu"; menu.className = "mk";
      menu.innerHTML = `<p>Design mockup of the page at phone width, over a scrubbed capture. Pick a variant; the page reloads on it.</p>
        ${seg("Page", "phone", ["on", "current"], phone)}${seg("Navigator", "nav", NAVS, nav)}${seg("Kanban", "kb", KBS, kb)}${seg("Text size", "fs", ["100", "125", "150"], fs)}`;
      chip.addEventListener("click", () => menu.classList.toggle("open"));
      menu.addEventListener("click", (e) => { const b = e.target.closest("button[data-k]"); if (b) { if (b.dataset.k !== "s") q.delete("s"); go(b.dataset.k, b.dataset.v); } });
      document.body.append(chip, menu);
    });
    return;
  }

  window.__COMPARE__ = true;
  const VW = 390, VH = 844;
  style(`${SEG}
    #cmp { position: fixed; inset: 0; overflow: auto; padding: 14px 20px 28px; box-sizing: border-box; font: 12px Inter, system-ui, sans-serif; color: var(--ink-2); }
    #cmp h1 { margin: 0 0 4px; font-size: 15px; font-weight: 500; color: var(--ink); }
    #cmp .lede { margin: 0 0 10px; max-width: 1100px; color: var(--muted); line-height: 1.55; }
    #cmp .lede b { font-weight: 500; color: var(--ink-3); }
    #cmp .bar { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; margin-bottom: 14px; }
    #cmp .cols { display: flex; flex-wrap: wrap; gap: 24px; align-items: flex-start; }
    #cmp .side h2 { margin: 0 0 6px; font-size: 12.5px; font-weight: 500; color: var(--ink); }
    #cmp .side h2 a { margin-left: 8px; font-weight: 400; color: var(--agent-text); text-decoration: none; }
    #cmp .vp { position: relative; overflow: hidden; border: 1px solid color-mix(in srgb, var(--slate) 25%, transparent); border-radius: 14px; }
    #cmp iframe { position: absolute; left: 0; top: 0; border: 0; transform-origin: 0 0; background: var(--bg0); }
    #cmp .try { flex: 1 1 300px; max-width: 460px; min-width: 260px; line-height: 1.6; color: var(--ink-3); }
    #cmp .try h2 { margin: 0 0 6px; font-size: 12.5px; font-weight: 500; color: var(--ink); }
    #cmp .try ol { margin: 0 0 14px; padding-left: 18px; }
    #cmp .try li { margin-bottom: 4px; }
    #cmp .try b { font-weight: 500; color: var(--ink); }
    #cmp .try .q { color: var(--run-text); }`);
  const frame = (ph) => `${location.pathname}?${new URLSearchParams({ frame: "1", phone: ph, view, fs, nav, kb, ...(ph === "on" && s !== "none" ? { s } : {}), ...(q.get("lane") ? { lane: q.get("lane") } : {}) })}`;
  const root = document.getElementById("root");
  root.innerHTML = `<div id="cmp" class="mk">
    <h1>StarPulse at phone width (390 × 844)</h1>
    <p class="lede">Left: today. Under 900 px the navigator and the rail are hidden, so only the address switches between the Star Map, the
      Kanban, the DAGs and the Admin view, and those three views keep their wide layouts. Right: the proposal, every part of it a real
      control over a scrubbed capture. <b>Navigator</b>: a bottom bar holding every view with More opening the real navigator as a sheet
      (recommended), or one corner button opening it as a drawer, or as a full-screen overlay. <b>Kanban</b>: one lane at a time, picked on
      a strip of the lanes (recommended) or by tapping a lane's header in a stack. <b>DAGs</b>: each row on two lines.
      <b>Admin</b>: each setting's name over its control. Each frame is the page at 390 × 844 at its real size.</p>
    <div class="bar">${seg("View", "view", VIEWS, view)}${seg("State", "s", STATES, s)}${seg("Navigator", "nav", NAVS, nav)}${seg("Kanban", "kb", KBS, kb)}${seg("Text size", "fs", ["100", "125", "150"], fs)}</div>
    <div class="cols">${[["current", "Today"], ["on", `Proposed: ${NAMES[nav]}${view === "kanban" ? `, ${NAMES[kb]}` : ""}`]].map(([ph, t]) => `<section class="side">
      <h2>${t}<a href="${frame(ph)}" target="_blank">open alone</a></h2>
      <div class="vp"><iframe title="${t}" src="${frame(ph)}" width="${VW}" height="${VH}"></iframe></div></section>`).join("")}
      <section class="try"><h2>What to try in the right-hand frame</h2><ol>
        <li><b>Switch views</b>: tap Star Map, Kanban, DAGs, Admin on the bar. With Navigator: drawer or full overlay, tap the ☰ button top left, then a view.</li>
        <li><b>The rest of the navigator</b>: tap More (or ☰). The sheet is the page's own navigator: status line, search, the view's outline or leaderboard. A view, a search hit, ✕, Escape or a tap outside closes it.</li>
        <li><b>Kanban lanes</b>: tap a ring-and-count tab; the lane showing keeps its header. With Kanban: stacked lanes, tap a lane's header. Scroll the lane; tap a card for the task, full screen.</li>
        <li><b>Kanban toolbar</b>: the filter chips wrap; the scheduler strip takes its own lines.</li>
        <li><b>DAGs</b>: a row is the DAG and its last run over its steps, pool and board tie. Tap a row for the DAG, full screen; ▶ still runs it.</li>
        <li><b>Admin</b>: drag the font size slider; every control fits the width.</li>
        <li><b>Text size</b>: 100%, 125%, 150% above reloads both frames at that Admin text size.</li></ol>
        <h2>Decisions this render asks for</h2><ol>
        <li class="q">Navigator: bottom bar, drawer or full overlay?</li>
        <li class="q">Kanban: lane strip or stacked lanes?</li>
        <li class="q">A card moves between lanes from its task view's Status at phone width, not by drag: accept?</li>
        <li class="q">The right rail (Recent, legend) stays hidden at phone width: accept, or does Recent need a place?</li>
        <li class="q">An open DAG's chart keeps its readable size and scrolls sideways inside its own box (State: DAG open); fitted to 390 px its step names were 4 px tall. Accept this one exception to "nothing scrolls sideways"?</li></ol></section>
    </div></div>`;
  root.addEventListener("click", (e) => { const b = e.target.closest("button[data-k]"); if (b) go(b.dataset.k, b.dataset.v); });
  // the frames keep their real size while the window is tall enough, else both scale down together
  const fit = () => {
    const sc = Math.min(1, Math.max(0.5, (innerHeight - 40) / VH));
    for (const vp of root.querySelectorAll(".vp")) {
      vp.style.width = `${VW * sc}px`;
      vp.style.height = `${VH * sc}px`;
      vp.firstElementChild.style.transform = `scale(${sc})`;
    }
  };
  addEventListener("resize", fit);
  fit();
})();
