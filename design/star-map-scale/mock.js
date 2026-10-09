// Design mockup layer (Star Map sizing per resolution), never part of the page. The page above is a scrubbed capture of the
// real StarPulse page, built from a source copy (star-map-scale-src.patch) that adds a grid sizing rule: each Board state gets one cell
// of the canvas and one fixed footprint (task band, moon orbit, clearance R), busy or empty; the zoom is the largest that fits a cell,
// and the labels scale with the sun, clamped to 12-20 px. Without ?frame this layer draws the review frame: the page at a chosen
// resolution, today's rendering beside the proposal, each in an iframe at its real CSS size and scaled down to fit, with a table read
// live from each frame's flowProbe(). It runs before the page's module.
//   ?res=1920x1080   the resolution compared (the buttons set it)       ?fs=100|125|150   the Admin text size
//   ?layout=auto|row|wrap   the proposal's cell layout (auto picks the larger cells; row keeps today's columns)
//   ?frame=1&sizing=current|grid&rails=off   one page alone, as each iframe loads it
(() => {
  const q = new URLSearchParams(location.search), F = window.__FLOW_FIXTURE__;
  const fs = Number(q.get("fs") || 100), layout = q.get("layout") || "auto";
  try {
    const k = "fv.admin.prefs", p = JSON.parse(localStorage.getItem(k) || "{}");
    p.scale = fs;
    localStorage.setItem(k, JSON.stringify(p));
  } catch { /* storage off: the page keeps 100% */ }

  if (q.has("frame")) {
    if ((q.get("sizing") || "grid") === "grid") window.__SIZING__ = { mode: "grid", layout, text: fs / 100 };
    // a phone's width is spent by the 250 px rails today: rails=off shows the canvas the sizing rule gets once they fold
    if (q.get("rails") === "off") {
      const st = document.createElement("style");
      st.textContent = ":root { --nav: 0px !important; --rail: 0px !important; } #nav, #rail { display: none !important; }";
      document.head.append(st);
    }
    return;
  }

  window.__COMPARE__ = true;
  const RES = ["390x844", "1366x768", "1600x1000", "1920x1080", "2560x1440", "3440x1440", "3840x2160"];
  const res = RES.includes(q.get("res")) ? q.get("res") : "1920x1080";
  const [VW, VH] = res.split("x").map(Number), phone = VW < 700;
  const tasks = {};
  for (const a of (F?.flows.find((f) => f.name === "board")?.agents ?? [])) tasks[a.state] = (tasks[a.state] || 0) + 1;

  const css = document.createElement("style");
  css.textContent = `
    #cmp { position: fixed; inset: 0; overflow: auto; padding: 14px 20px 28px; box-sizing: border-box; font-size: calc(12px * var(--fs)); color: var(--ink-2); }
    #cmp h1 { margin: 0 0 4px; font-size: calc(15px * var(--fs)); font-weight: 500; color: var(--ink); }
    #cmp .lede { margin: 0 0 10px; max-width: 1100px; color: var(--muted); line-height: 1.5; }
    #cmp .bar { display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: center; margin-bottom: 12px; }
    #cmp .lb { color: var(--ink-3); font-size: calc(11.5px * var(--fs)); }
    #cmp .seg { display: inline-flex; border-radius: 5px; border: 1px solid color-mix(in srgb, var(--slate) 25%, transparent); overflow: hidden; }
    #cmp .seg button { all: unset; padding: 2px 12px; font-size: calc(11.5px * var(--fs)); color: var(--ink-3); }
    #cmp .seg button + button { border-left: 1px solid color-mix(in srgb, var(--slate) 18%, transparent); }
    #cmp .seg button.on { background: color-mix(in srgb, var(--agent) 22%, transparent); color: var(--ink); }
    #cmp .seg button:hover, #cmp .seg button:focus-visible { background: color-mix(in srgb, var(--agent) 12%, transparent); }
    #cmp .pair { display: grid; gap: 16px; }
    #cmp .side h2 { margin: 0 0 6px; font-size: calc(12.5px * var(--fs)); font-weight: 500; color: var(--ink); }
    #cmp .side h2 a { margin-left: 8px; font-weight: 400; color: var(--agent-text); text-decoration: none; }
    #cmp .vp { position: relative; overflow: hidden; border: 1px solid color-mix(in srgb, var(--slate) 18%, transparent); border-radius: 4px; }
    #cmp iframe { position: absolute; left: 0; top: 0; border: 0; transform-origin: 0 0; background: var(--bg0); }
    #cmp table { margin-top: 8px; border-collapse: collapse; font-variant-numeric: tabular-nums; }
    #cmp th, #cmp td { padding: 2px 10px 2px 0; text-align: right; white-space: nowrap; }
    #cmp th:first-child, #cmp td:first-child { text-align: left; }
    #cmp th { font-weight: 400; color: var(--muted); }
    #cmp .sum { margin-top: 6px; color: var(--ink-3); }
    #cmp .sum b { font-weight: 500; color: var(--ink); }`;
  document.head.append(css);

  const go = (k, v) => { q.set(k, v); location.search = q.toString(); };
  const seg = (label, key, vals, cur, names = {}) => `<span class="lb">${label}</span><span class="seg">${
    vals.map((v) => `<button data-k="${key}" data-v="${v}" class="${v === cur ? "on" : ""}">${names[v] ?? v}</button>`).join("")}</span>`;
  const frame = (sizing) => {
    const p = new URLSearchParams({ frame: "1", sizing, fs: String(fs), layout });
    if (phone) p.set("rails", "off");
    return `${location.pathname}?${p}`;
  };
  const root = document.getElementById("root");
  root.innerHTML = `<div id="cmp">
    <h1>Star Map size per screen resolution</h1>
    <p class="lede">Left: today, every body sized in world units and the whole Board fit to the canvas width. Right: the proposal, one cell
      of the canvas per state, one fixed footprint per state busy or empty, labels scaled with the sun. Each frame is the page at the
      chosen resolution, scaled down to fit here; open a side alone to see it at its real size. The table is read live from each frame.</p>
    <div class="bar">${seg("Resolution", "res", RES, res)}${seg("Text size", "fs", ["100", "125", "150"], String(fs), { 100: "100%", 125: "125%", 150: "150%" })}${
      seg("Proposal layout", "layout", ["auto", "row", "wrap"], layout)}</div>
    <div class="pair">${[["current", "Today"], ["grid", "Proposed: grid cell, fixed footprint"]].map(([s, t]) => `<section class="side" data-s="${s}">
      <h2>${t}<a href="${frame(s)}" target="_blank">open alone</a></h2>
      <div class="vp"><iframe title="${t}" src="${frame(s)}" width="${VW}" height="${VH}"></iframe></div>
      <div class="sum"></div><table></table></section>`).join("")}</div></div>`;
  root.addEventListener("click", (e) => { const b = e.target.closest("button[data-k]"); if (b) go(b.dataset.k, b.dataset.v); });

  // side by side when the two fit at a useful scale, else stacked; each frame keeps its aspect
  const pair = root.querySelector(".pair");
  const fitFrames = () => {
    const avail = root.firstElementChild.clientWidth - 40, side = VW / VH < 1 || avail > 1400;
    pair.style.gridTemplateColumns = side ? "1fr 1fr" : "1fr";
    const colW = side ? (avail - 16) / 2 : avail, s = Math.min(1, colW / VW, (innerHeight * (side ? 0.62 : 0.5)) / VH);
    for (const vp of root.querySelectorAll(".vp")) {
      vp.style.width = `${VW * s}px`;
      vp.style.height = `${VH * s}px`;
      vp.firstElementChild.style.transform = `scale(${s})`;
    }
  };
  addEventListener("resize", fitFrames);
  fitFrames();

  const SUN_R = 34, n1 = (x) => x.toFixed(1);
  const read = () => {
    for (const side of root.querySelectorAll(".side")) {
      let pr;
      try { pr = side.querySelector("iframe").contentWindow.flowProbe?.(); } catch { pr = null; }
      if (!pr?.states?.length) continue;
      const k = pr.fit, sun = SUN_R * k, grid = side.dataset.s === "grid";
      const label = (grid ? Math.min(20, Math.max(12, 0.45 * sun)) : 13) * fs / 100;
      const rows = [...pr.states].sort((a, b) => a.x - b.x || a.y - b.y);
      const Rs = rows.map((s) => s.r), lo = Math.min(...Rs), hi = Math.max(...Rs);
      side.querySelector(".sum").innerHTML = `canvas ${Math.round(pr.canvas.w)}x${Math.round(pr.canvas.h)} · zoom <b>${k.toFixed(3)}</b> · sun <b>${n1(sun)} px</b>
        (${(sun / pr.canvas.h * 100).toFixed(2)}% of height) · state name <b>${n1(label)} px</b> · footprint R ${
        hi - lo < 0.5 ? `<b>${n1(hi)} px for every state</b>` : `${n1(lo)}–${n1(hi)} px, by load`}`;
      side.querySelector("table").innerHTML = `<tr><th>state</th><th>tasks</th><th>R px</th></tr>${
        rows.map((s) => `<tr><td>${s.id}</td><td>${tasks[s.id] ?? 0}</td><td>${n1(s.r)}</td></tr>`).join("")}`;
    }
  };
  setInterval(read, 1000);
})();
