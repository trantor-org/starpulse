// Mockup layer (TASK-2633): the Admin view injected over a self-contained capture of the live StarPulse page.
// Client settings persist in localStorage; the server's history window is simulated, including its refusals.
(() => {
  const KEY = "fv.admin.prefs";
  const DEFAULTS = { scale: 100, motion: true, defaultView: "constellation", density: "comfortable", clock: "24" };
  const STATES = {
    admin: { view: "admin" },
    "admin-large": { view: "admin", scale: 130 },
    "map-large": { view: "constellation", scale: 130 },
    "kanban-large": { view: "kanban", scale: 130 },
    "kanban-compact": { view: "kanban", density: "compact" },
    "clock12": { view: "constellation", clock: "12" },
    "reduce-motion": { view: "constellation", motion: false },
    "history-refused": { view: "admin", refuse: true },
  };
  const qs = new URLSearchParams(location.search);
  const preset = STATES[qs.get("s")] || STATES[location.hash.slice(1)] || null;
  let prefs;
  try { prefs = { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") }; } catch { prefs = { ...DEFAULTS }; }
  if (preset) {
    prefs = { ...DEFAULTS };
    for (const k of Object.keys(DEFAULTS)) if (k in preset) prefs[k] = preset[k];
  }
  const save = () => { try { if (!preset) localStorage.setItem(KEY, JSON.stringify(prefs)); } catch {} };

  // ---- the address the app reads, fixed before its module runs ----
  let admin = false;
  {
    const p = new URLSearchParams(location.search);
    const want = preset ? preset.view : p.get("view") || (prefs.defaultView === "kanban" ? "kanban" : null);
    if (want === "admin") admin = true;
    if (want === "kanban" || want === "admin") p.set("view", want); else p.delete("view");
    p.delete("s");
    const s = p.toString();
    try { history.replaceState(null, "", location.pathname + (s ? "?" + s : "") + location.hash); } catch {}
  }

  // ---- font scale: every px font size in the page's own sheets, and every canvas font ----
  const originals = new Map();
  function walk(rules, fn) {
    for (const r of rules) {
      if (r.cssRules && !(r instanceof CSSStyleRule)) walk(r.cssRules, fn);
      else if (r.style) fn(r);
    }
  }
  const scalePx = (v, f) => v.replace(/(\d*\.?\d+)px/g, (_, n) => `${+(n * f).toFixed(2)}px`);
  function applyScale() {
    const f = prefs.scale / 100;
    for (const sheet of document.styleSheets) {
      let rules;
      try { rules = sheet.cssRules; } catch { continue; } // the web-font sheet is cross-origin
      walk(rules, (r) => {
        if (!originals.has(r)) originals.set(r, { fs: r.style.fontSize, font: r.style.font });
        const o = originals.get(r);
        if (o.fs && o.fs.includes("px")) r.style.fontSize = scalePx(o.fs, f);
        if (o.font && o.font.includes("px")) r.style.font = scalePx(o.font, f);
      });
    }
  }
  const desc = Object.getOwnPropertyDescriptor(CanvasRenderingContext2D.prototype, "font");
  Object.defineProperty(CanvasRenderingContext2D.prototype, "font", {
    get() { return desc.get.call(this); },
    set(v) { desc.set.call(this, prefs.scale === 100 ? v : scalePx(String(v), prefs.scale / 100)); },
  });

  // ---- reduce motion: no CSS animation, and the canvas redraws once a second unless you are panning or hovering ----
  let lastInput = 0;
  addEventListener("pointermove", () => (lastInput = performance.now()), true);
  addEventListener("wheel", () => (lastInput = performance.now()), true);
  const raf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = (cb) => {
    if (prefs.motion || performance.now() - lastInput < 600) return raf(cb);
    return setTimeout(() => raf(cb), 1000);
  };

  // ---- clock: 24h text in the page's time slots rewritten to 12h ----
  const H24 = /\b([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?\b(?![:\d]|\s?[ap]\.?m)/gi;
  const to12 = (s) => s.replace(H24, (_, h, m, sec) => `${(+h % 12) || 12}:${m}${sec ? ":" + sec : ""} ${+h < 12 ? "am" : "pm"}`);
  const TIMED = "#clock, #nav .sub, #feed, #tip, #panel, #kbm, #kb .ago, .hud, #admin .when";
  const H12 = /\b(1[0-2]|0?[1-9]):([0-5]\d)(:[0-5]\d)?\s?([ap])\.?m\.?(?![a-z])/gi;
  const to24 = (s) => s.replace(H12, (_, h, m, sec, ap) => `${String((+h % 12) + (/p/i.test(ap) ? 12 : 0)).padStart(2, "0")}:${m}${sec || ""}`);
  function rewrite(root) {
    if (!root) return;
    const conv = prefs.clock === "12" ? to12 : to24;
    const els = root.nodeType === 1 && root.matches?.(TIMED) ? [root] : [];
    for (const el of els.concat([...(root.querySelectorAll?.(TIMED) ?? [])])) {
      const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      for (let n; (n = w.nextNode()); ) { const t = conv(n.data); if (t !== n.data) n.data = t; }
    }
  }

  // ---- the server: a simulated history-window endpoint ----
  const server = { hours: 6, declared: 6, changedAt: null };
  function putHistory(hours) {
    return new Promise((ok, fail) => setTimeout(() => {
      if (!Number.isFinite(hours)) return fail("history window must be a number of hours");
      if (hours < 1 || hours > 72) return fail(`history window must be between 1 and 72 hours; got ${hours}`);
      server.hours = hours; server.changedAt = new Date(); ok(server);
    }, 450));
  }

  // ---- DOM ----
  const css = `
    #nav .admin-sec { margin: auto -18px 0 !important; padding-top: 10px; border-top: 1px solid rgba(148,163,184,.08); }
    #nav .admin-sec .node { padding-left: 15px; width: 100%; }
    #nav .admin-sec .t { margin-left: 9px; transition: opacity .2s; }
    #nav.folded .admin-sec .t { opacity: 0; visibility: hidden; }
    #nav .admin-sec svg { flex: none; fill: none; stroke: currentColor; stroke-width: 1.3; }
    body.admin #nav .views:not(.admin-sec) .node.on { background: none; box-shadow: none; color: inherit; }
    body.admin #nav > section.away { display: none; }
    body.admin canvas:not(#ad-pv), body.admin #tip, body.admin #panel, body.admin #kb, body.admin .hud { visibility: hidden !important; }
    #admin { position: fixed; z-index: 3; top: 0; bottom: 0; left: calc(var(--nav) + 20px); right: calc(var(--rail) + 20px); display: none; flex-direction: column;
      font-size: 12px; color: var(--ink); transition: left .3s cubic-bezier(.4,0,.2,1); overflow-y: auto; }
    #nav.folded ~ #admin { left: calc(var(--nav-fold) + 20px); }
    body.admin #admin { display: flex; }
    #admin header { display: flex; align-items: center; gap: 14px; height: 64px; flex: none; }
    #admin header .title { font-size: 13px; font-weight: 500; letter-spacing: .32em; text-transform: uppercase; opacity: .85; }
    #admin header .count { font-size: 11px; color: var(--muted); }
    #admin .grid { display: grid; grid-template-columns: minmax(420px, 640px) minmax(280px, 1fr); gap: 20px; align-items: start; padding-bottom: 24px; }
    #admin .card { border-radius: 10px; background: rgba(12,19,34,.85); border: 1px solid rgba(148,163,184,.13); }
    #admin .card + .card { margin-top: 16px; }
    #admin .card h2 { margin: 0; display: flex; align-items: baseline; gap: 10px; padding: 12px 16px 10px; font-size: 11px; font-weight: 500; letter-spacing: .2em;
      text-transform: uppercase; color: #94a3b8; border-bottom: 1px solid rgba(148,163,184,.08); }
    #admin .card h2 .c { font-size: 11px; letter-spacing: 0; text-transform: none; font-weight: 400; color: var(--muted); }
    #admin .row { display: grid; grid-template-columns: 150px 1fr; gap: 14px; align-items: center; padding: 12px 16px; border-top: 1px solid rgba(148,163,184,.06); }
    #admin .row:first-of-type { border-top: 0; }
    #admin .lb { font-size: 12px; color: #cbd5e1; } #admin .hint { margin-top: 3px; font-size: 10.5px; color: var(--muted); line-height: 1.5; }
    #admin .seg { display: inline-flex; border: 1px solid rgba(148,163,184,.2); border-radius: 6px; overflow: hidden; }
    #admin .seg button { all: unset; cursor: pointer; padding: 4px 12px; font-size: 11.5px; color: #b8c4d8; }
    #admin .seg button + button { border-left: 1px solid rgba(148,163,184,.2); }
    #admin .seg button[aria-pressed=true] { background: rgba(167,139,250,.18); color: #ede9fe; }
    #admin .seg button:focus-visible, #admin .sw:focus-visible, #admin .btn:focus-visible { outline: 1px solid #a78bfa; outline-offset: 1px; }
    #admin .scale { display: flex; align-items: center; gap: 12px; }
    #admin input[type=range] { flex: 1; accent-color: #a78bfa; }
    #admin .pct { width: 44px; text-align: right; font-variant-numeric: tabular-nums; font-size: 12px; }
    #admin .ticks { display: flex; justify-content: space-between; margin: 2px 56px 0 0; font-size: 10px; color: #475569; }
    #admin .ticks button { all: unset; cursor: pointer; } #admin .ticks button:hover { color: var(--ink); }
    #admin .sw { all: unset; cursor: pointer; position: relative; width: 30px; height: 16px; border-radius: 8px; background: rgba(148,163,184,.25); transition: background .15s; }
    #admin .sw::after { content: ""; position: absolute; top: 2px; left: 2px; width: 12px; height: 12px; border-radius: 50%; background: #dbe4f3; transition: left .15s; }
    #admin .sw[aria-checked=true] { background: #7c3aed; } #admin .sw[aria-checked=true]::after { left: 16px; }
    #admin .btn { all: unset; cursor: pointer; padding: 4px 12px; border-radius: 6px; border: 1px solid rgba(148,163,184,.25); color: #b8c4d8; font-size: 11.5px; }
    #admin .btn.go { border-color: rgba(52,211,153,.45); color: #34d399; background: rgba(52,211,153,.08); }
    #admin .btn[disabled] { opacity: .45; cursor: default; }
    #admin .hours { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    #admin .hours input { box-sizing: border-box; width: 70px; height: 26px; padding: 0 8px; border-radius: 6px; border: 1px solid rgba(148,163,184,.2); background: rgba(8,13,26,.7);
      color: var(--ink); font: inherit; font-size: 12px; outline: none; font-variant-numeric: tabular-nums; }
    #admin .hours input:focus { border-color: #a78bfa; }
    #admin .chips { display: flex; gap: 4px; } #admin .chips button { all: unset; cursor: pointer; padding: 1px 7px; border-radius: 4px; background: rgba(148,163,184,.1); font-size: 10.5px; color: #94a3b8; }
    #admin .chips button:hover { color: var(--ink); }
    #admin .refusal { margin-top: 8px; padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(251,113,133,.35); background: rgba(60,14,28,.6); color: #fecdd3; font-size: 11px; line-height: 1.5; }
    #admin .refusal .k { color: #fda4af; font-size: 10.5px; margin-bottom: 2px; }
    #admin .ok { margin-top: 8px; font-size: 11px; color: #34d399; }
    #admin .foot { padding: 10px 16px 12px; font-size: 10.5px; color: #475569; border-top: 1px solid rgba(148,163,184,.06); display: flex; gap: 10px; align-items: center; }
    #admin .foot .btn { margin-left: auto; }
    #admin .pv { padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 14px; }
    #admin .pv canvas { position: static; display: block; width: 100%; height: 120px; cursor: default; border-radius: 8px; background: radial-gradient(circle at 50% 40%, #0d1528, #05070d 70%); }
    #admin .pvcard { box-sizing: border-box; padding: 8px 9px 8px 10px; border-radius: 7px; background: rgba(12,19,34,.92); border: 1px solid rgba(148,163,184,.13); line-height: 1.4; }
    body.compact #admin .pvcard { padding: 4px 8px; }
    #admin .pvcard .top { display: flex; align-items: center; gap: 6px; font-size: 10.5px; color: var(--muted); }
    #admin .pvcard .id { margin-right: auto; font-family: "JetBrains Mono", ui-monospace, monospace; color: #94a3b8; }
    #admin .pvcard .pr { display: flex; align-items: center; gap: 4px; font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 10px; padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(148,163,184,.2); color: #94a3b8; }
    #admin .pvcard .pr i { width: 6px; height: 6px; border-radius: 50%; background: #34d399; }
    #admin .pvcard .t { margin: 4px 0 6px; color: var(--ink); font-size: 12px; }
    body.compact #admin .pvcard .t { margin: 2px 0 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    #admin .pvcard .foot2 { display: flex; gap: 4px; font-size: 10px; color: var(--muted); }
    body.compact #admin .pvcard .foot2 { display: none; }
    #admin .pvcard .lab { padding: 0 5px; border-radius: 3px; background: rgba(148,163,184,.10); color: #94a3b8; line-height: 15px; }
    #admin .pvk { font-size: 10px; letter-spacing: .2em; text-transform: uppercase; color: var(--muted); }
    #admin .when { font-variant-numeric: tabular-nums; }
    body.compact #kb .col .body { gap: 4px; padding: 6px; }
    body.compact #kb .card { padding: 4px 8px 4px 9px; }
    body.compact #kb .card .t { margin: 2px 0 2px; -webkit-line-clamp: 1; }
    body.compact #kb .card .foot { display: none; }
    body.compact #kb .mach { margin-bottom: 2px; }
    body.still *, body.still *::before, body.still *::after { animation: none !important; transition: none !important; }
  `;
  const gear = `<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="1.8"/><path d="M6 .9v1.6M6 9.5v1.6M.9 6h1.6M9.5 6h1.6M2.4 2.4l1.1 1.1M8.5 8.5l1.1 1.1M2.4 9.6l1.1-1.1M8.5 3.5l1.1-1.1"/></svg>`;
  const seg = (name, opts, cur) => `<div class="seg" role="group" data-k="${name}">${opts.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${v === cur}">${l}</button>`).join("")}</div>`;
  const fmtWhen = (d) => d ? `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` : "";

  function view() {
    return `<header><span class="title">Admin</span><span class="count">settings for this browser and for the StarPulse server</span></header>
    <div class="grid"><div>
      <section class="card"><h2>This browser <span class="c">kept on this device only</span></h2>
        <div class="row"><div><div class="lb">Font size</div><div class="hint">Panels, Kanban cards and Star Map labels</div></div>
          <div><div class="scale"><input id="ad-scale" type="range" min="85" max="150" step="5" value="${prefs.scale}" aria-label="Font size"><span class="pct">${prefs.scale}%</span></div>
          <div class="ticks">${[85, 100, 115, 130, 150].map((v) => `<button type="button" data-scale="${v}">${v}%</button>`).join("")}</div></div></div>
        <div class="row"><div><div class="lb">Motion</div><div class="hint">Pulses travel and cards animate</div></div>
          <div><button type="button" class="sw" role="switch" id="ad-motion" aria-checked="${prefs.motion}" aria-label="Motion"></button></div></div>
        <div class="row"><div><div class="lb">Opens on</div><div class="hint">When the address names no view</div></div>
          <div>${seg("defaultView", [["constellation", "Star Map"], ["kanban", "Kanban"]], prefs.defaultView)}</div></div>
        <div class="row"><div><div class="lb">Kanban cards</div><div class="hint">Compact shows one title line, no labels</div></div>
          <div>${seg("density", [["comfortable", "Comfortable"], ["compact", "Compact"]], prefs.density)}</div></div>
        <div class="row"><div><div class="lb">Clock</div><div class="hint">Header clock, Recent feed, panels</div></div>
          <div>${seg("clock", [["24", "24-hour"], ["12", "12-hour"]], prefs.clock)}</div></div>
        <div class="foot">Changes apply as you make them.<button type="button" class="btn" id="ad-reset">Reset this browser</button></div>
      </section>
      <section class="card"><h2>Server <span class="c">shared by every viewer</span></h2>
        <div class="row"><div><div class="lb">History window</div><div class="hint">How far back a task's latest move on a machine counts</div></div>
          <div><div class="hours"><input id="ad-hours" inputmode="decimal" value="${server.hours}" aria-label="History window in hours"> hours
            <div class="chips">${[1, 6, 24, 72].map((h) => `<button type="button" data-h="${h}">${h}h</button>`).join("")}</div>
            <button type="button" class="btn go" id="ad-save" disabled>Save</button></div>
            <div class="hint">Default ${server.declared} h, declared in flow-view.service. <a href="#" id="ad-hreset" style="color:#c4b5fd">Reset to default</a></div>
            <div id="ad-hmsg"></div></div></div>
      </section>
    </div>
    <section class="card"><h2>Preview</h2><div class="pv">
      <div class="pvk">Star Map label</div><canvas id="ad-pv"></canvas>
      <div class="pvk">Kanban card</div>
      <div class="pvcard"><div class="top"><span class="id">TASK-2633</span><span class="pr"><i></i>#2094</span></div>
        <div class="t">Design the StarPulse settings page (font size first)</div>
        <div class="foot2"><span class="lab">feature</span><span class="lab">size-3</span><span class="lab">needs-human</span></div></div>
    </div></section></div>`;
  }

  function drawPreview() {
    const c = document.getElementById("ad-pv"); if (!c) return;
    const r = c.getBoundingClientRect(), dpr = devicePixelRatio || 1;
    c.width = r.width * dpr; c.height = r.height * dpr;
    const cx = c.getContext("2d"); cx.scale(dpr, dpr);
    const x = r.width / 2, y = r.height / 2 - 14;
    cx.strokeStyle = "rgba(167,139,250,.8)"; cx.lineWidth = 1; cx.beginPath(); cx.arc(x, y, 9, 0, 7); cx.stroke();
    cx.textAlign = "center"; cx.textBaseline = "middle"; cx.letterSpacing = "0.6px";
    cx.font = "300 12.5px Inter, system-ui, sans-serif"; cx.fillStyle = "rgba(207,217,234,.9)";
    const fs = 12.5 * prefs.scale / 100;
    cx.fillText("In Progress", x, y + 14 + fs / 2 + 4);
    cx.font = "300 10.5px Inter, system-ui, sans-serif"; cx.fillStyle = "rgba(148,163,184,.6)";
    cx.fillText("4 tasks", x, y + 14 + fs * 1.5 + 8);
  }

  function apply() {
    applyScale();
    document.body.classList.toggle("compact", prefs.density === "compact");
    document.body.classList.toggle("still", !prefs.motion);
    rewrite(document.body);
    drawPreview();
    window.dispatchEvent(new Event("resize")); // the renderer refits its labels, and the preview redraws
  }

  function setAdmin(on, push) {
    admin = on;
    document.body.classList.toggle("admin", on);
    document.querySelector("#nav .admin-sec .node")?.classList.toggle("on", on);
    document.querySelector("#nav .admin-sec .node")?.classList.toggle("here", on);
    if (push) {
      const p = new URLSearchParams(location.search);
      p.delete("s");
      if (on) p.set("view", "admin");
      history.pushState(null, "", location.pathname + "?" + p.toString());
    }
    if (on) requestAnimationFrame(() => requestAnimationFrame(drawPreview));
  }

  function mountNav() {
    const nav = document.getElementById("nav"); if (!nav) return;
    let sec = nav.querySelector(".admin-sec");
    if (!sec) {
      sec = document.createElement("section");
      sec.className = "admin-sec views";
      sec.innerHTML = `<button class="node" title="Admin">${gear}<span class="t">Admin</span><span class="n"></span></button>`;
      sec.querySelector("button").addEventListener("click", () => setAdmin(true, true));
      setAdmin(admin, false);
    }
    if (nav.lastElementChild !== sec) nav.appendChild(sec);
    sec.querySelector(".node").classList.toggle("on", admin);
    sec.querySelector(".node").classList.toggle("here", admin);
  }

  function wire(root) {
    root.querySelector("#ad-scale").addEventListener("input", (e) => { prefs.scale = +e.target.value; root.querySelector(".pct").textContent = prefs.scale + "%"; save(); apply(); });
    root.querySelectorAll("[data-scale]").forEach((b) => b.addEventListener("click", () => { prefs.scale = +b.dataset.scale; root.querySelector("#ad-scale").value = prefs.scale; root.querySelector(".pct").textContent = prefs.scale + "%"; save(); apply(); }));
    root.querySelector("#ad-motion").addEventListener("click", (e) => { prefs.motion = !prefs.motion; e.currentTarget.setAttribute("aria-checked", prefs.motion); save(); apply(); });
    root.querySelectorAll(".seg").forEach((g) => g.addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      prefs[g.dataset.k] = b.dataset.v;
      g.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
      save();
      apply();
    }));
    root.querySelector("#ad-reset").addEventListener("click", () => { prefs = { ...DEFAULTS }; save(); render(); apply(); });
    const inp = root.querySelector("#ad-hours"), sv = root.querySelector("#ad-save"), msg = root.querySelector("#ad-hmsg");
    const dirty = () => { sv.disabled = inp.value.trim() === String(server.hours); };
    inp.addEventListener("input", () => { msg.innerHTML = ""; dirty(); });
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter" && !sv.disabled) sv.click(); if (e.key === "Escape") { inp.value = server.hours; dirty(); } });
    root.querySelectorAll("[data-h]").forEach((b) => b.addEventListener("click", () => { inp.value = b.dataset.h; msg.innerHTML = ""; dirty(); inp.focus(); }));
    root.querySelector("#ad-hreset").addEventListener("click", (e) => { e.preventDefault(); inp.value = server.declared; dirty(); sv.click(); });
    sv.addEventListener("click", () => {
      sv.disabled = true; sv.textContent = "Saving…";
      putHistory(Number(inp.value.trim()))
        .then((s) => { msg.innerHTML = `<div class="ok">Saved: every viewer counts the last ${s.hours} h from the next snapshot · <span class="when">${fmtWhen(s.changedAt)}</span></div>`; rewrite(msg); })
        .catch((why) => { msg.innerHTML = `<div class="refusal"><div class="k">the server refused the change</div>${why}</div>`; })
        .finally(() => { sv.textContent = "Save"; dirty(); });
    });
    if (preset?.refuse) { inp.value = "200"; dirty(); sv.click(); }
  }

  function render() {
    const el = document.getElementById("admin");
    el.innerHTML = view();
    wire(el);
  }

  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  addEventListener("DOMContentLoaded", () => {
    const el = document.createElement("div");
    el.id = "admin";
    document.body.appendChild(el);
    render();
    const mo = new MutationObserver((recs) => {
      mountNav();
      for (const r of recs) rewrite(r.target.nodeType === 3 ? r.target.parentElement : r.target);
      // the app's own nav buttons leave Admin
    });
    mo.observe(document.body, { childList: true, subtree: true, characterData: true });
    document.addEventListener("click", (e) => {
      if (e.target.closest("#nav .views:not(.admin-sec) .node") && admin) {
        setAdmin(false, false);
        const p = new URLSearchParams(location.search); p.delete("view"); p.delete("s");
        history.replaceState(null, "", location.pathname + (p.toString() ? "?" + p : ""));
      }
    }, true);
    addEventListener("popstate", () => setAdmin(new URLSearchParams(location.search).get("view") === "admin", false));
    mountNav();
    document.body.classList.toggle("admin", admin);
    setTimeout(apply, 0);
    addEventListener("load", apply);
    addEventListener("resize", () => admin && drawPreview());
  });
})();
