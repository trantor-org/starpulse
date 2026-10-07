// Navigator mockup layer: a real Star Map icon in the navigator's Views, the Kanban search docked in the Star Map
// search's slot, an ✕ that clears either search while it holds text, and a strip magnifier while the navigator is folded.
// Injected over a scrubbed capture of the live page; it only adds elements and styles, so React keeps owning the page.
(() => {
  const STATES = {
    map: { view: "constellation" },
    "map-q": { view: "constellation", q: "review" },
    kanban: { view: "kanban" },
    "kanban-q": { view: "kanban", kq: "backup" },
    "kanban-label": { view: "kanban", kq: "kind", focus: true },
    "folded-kanban": { view: "kanban", kq: "backup", folded: true },
    "folded-map": { view: "constellation", folded: true },
  };
  const ICONS = ["constellation", "compass", "orbit", "chart", "sextant", "current"];
  const SIZES = [100, 125, 150];
  // a switcher choice survives the reload in sessionStorage too, for a frame that drops the query string
  let next = null;
  try { next = JSON.parse(sessionStorage.getItem("nv.next") || "null"); sessionStorage.removeItem("nv.next"); } catch {}
  const qs = new URLSearchParams(next && !new URLSearchParams(location.search).get("s") ? next : location.search);
  // a frame that passes only a bare #anchor can still link a state: #kanban-label
  if (!qs.get("s") && location.hash.slice(1) in STATES) qs.set("s", location.hash.slice(1));
  const sKey = qs.get("s") in STATES ? qs.get("s") : null;
  const preset = sKey ? STATES[sKey] : null;
  let icon = ICONS.includes(qs.get("icon")) ? qs.get("icon") : "constellation";
  const fs = SIZES.includes(+qs.get("fs")) ? +qs.get("fs") : null;

  // ---- a linked state seeds the page's own stores before the app reads them ----
  const store = (k, v) => { try { localStorage.setItem(k, v); } catch {} };
  const read = (k) => { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch { return null; } };
  if (preset) {
    store("fv.nav.folded", preset.folded ? "1" : "0");
    store("fv.kanban.prefs", JSON.stringify({ query: preset.kq || "", assignee: null, milestone: null, folded: [], hiddenMilestones: [], hiddenTasks: [] }));
    const p = new URLSearchParams(location.search);
    if (preset.view === "kanban") p.set("view", "kanban"); else p.delete("view");
    try { history.replaceState(null, "", location.pathname + "?" + p.toString()); } catch {}
  }
  if (fs) store("fv.admin.prefs", JSON.stringify({ ...(read("fv.admin.prefs") || {}), scale: fs }));
  document.documentElement.classList.add("nv-" + icon);
  if (qs.get("chrome") === "0") document.documentElement.classList.add("nv-nochrome");

  // ---- the icon concepts, drawn on a 24-unit grid and shown at 14 px in the glyph's place ----
  const SVG = {
    sextant: `<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <defs><mask id="nv-cut"><rect width="24" height="24" fill="#fff"/><path d="M17 10 L11.5 19.5 A11 11 0 0 0 22.5 19.5 Z" fill="#000" stroke="#000" stroke-width="3.4" stroke-linejoin="round"/></mask></defs>
      <g mask="url(#nv-cut)" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round">
        <path d="M1 5.5 L6.5 3.5 L12 5.5 L17 3.5 V15.5 L12 17.5 L6.5 15.5 L1 17.5 Z"/><path d="M6.5 3.5 V15.5 M12 5.5 V17.5" opacity=".6"/>
      </g>
      <g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round">
        <path d="M17 10 L11.5 19.5 A11 11 0 0 0 22.5 19.5 Z" fill="currentColor" fill-opacity=".14"/><path d="M17 10 L18.9 20.8"/>
      </g>
      <circle cx="17" cy="10" r="1.6" fill="currentColor"/>
    </svg>`,
    chart: `<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <circle cx="12" cy="12" r="9.3" fill="none" stroke="currentColor" stroke-width="1.6"/>
      <path d="M12 .6 V4 M12 20 V23.4 M.6 12 H4 M20 12 H23.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M12 6.3 L13.5 10.5 L17.7 12 L13.5 13.5 L12 17.7 L10.5 13.5 L6.3 12 L10.5 10.5 Z" fill="currentColor"/>
      <circle cx="17" cy="7.2" r="1" fill="currentColor"/><circle cx="7.4" cy="16.6" r=".8" fill="currentColor"/>
    </svg>`,
    constellation: `<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <path d="M3 17.5 L8.5 12 L13.5 14.5 L20 5 M13.5 14.5 L18.5 20.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" opacity=".65"/>
      <circle cx="3" cy="17.5" r="2" fill="currentColor"/><circle cx="8.5" cy="12" r="2.2" fill="currentColor"/><circle cx="13.5" cy="14.5" r="2" fill="currentColor"/>
      <circle cx="20" cy="5" r="2.5" fill="currentColor"/><circle cx="18.5" cy="20.5" r="1.7" fill="currentColor"/>
    </svg>`,
    compass: `<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <circle cx="12" cy="12" r="9.6" fill="none" stroke="currentColor" stroke-width="1.6"/>
      <path d="M12 4.2 L14.8 12 H9.2 Z" fill="currentColor"/><path d="M12 19.8 L9.2 12 H14.8 Z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>
    </svg>`,
    orbit: `<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <circle cx="12" cy="12" r="5" fill="currentColor"/>
      <ellipse cx="12" cy="12" rx="10.6" ry="3.9" transform="rotate(-28 12 12)" fill="none" stroke="currentColor" stroke-width="1.5"/>
      <circle cx="20.6" cy="3.6" r="1.1" fill="currentColor"/>
    </svg>`,
  };
  const MAG = `<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M15.4 15.4 L21 21" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>`;

  const css = `
  /* the Star Map entry's glyph: the chosen icon replaces the bare ring; "current" keeps today's ring for comparison */
  html:not(.nv-current) #nav section.views:not(.admin-sec) .node:first-of-type > i.g { border: 0; border-radius: 0; width: 14px !important; height: 14px !important; display: grid; place-items: center; }
  html:not(.nv-current) #nav section.views:not(.admin-sec) .node:first-of-type > i.g > svg { display: block; }
  html.nv-current #nav section.views:not(.admin-sec) .node:first-of-type > i.g > svg { display: none; }
  /* both searches: room for the ✕ at the right end */
  #q, #kb .filters > .fw:first-child input { padding-right: calc(24px * var(--fs)) !important; }
  #nav section.away:has(> #q) { position: relative; }
  /* the browser's own search-field clear button would draw a second ✕ beside ours */
  #q::-webkit-search-cancel-button, #kb .filters > .fw:first-child input::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; display: none; }
  .nv-x { all: unset; box-sizing: border-box; position: absolute; z-index: 1; top: 50%; right: 5px; transform: translateY(-50%); cursor: pointer; display: none; place-items: center;
    width: calc(18px * var(--fs)); height: calc(18px * var(--fs)); border-radius: 4px; color: var(--muted); font-size: calc(11px * var(--fs)); line-height: 1; }
  .nv-x.on { display: grid; }
  .nv-x:hover, .nv-x:focus-visible { color: var(--ink); background: rgba(148,163,184,.14); }
  /* the Kanban search leaves the toolbar for the slot the Star Map search holds, styled as that search */
  #kb .filters > .fw:first-child { position: fixed; left: 18px; top: var(--nv-sy, 166px); width: calc(var(--nav) - 36px); flex: none; z-index: 5; transition: opacity .2s, visibility 0s; }
  #kb .filters > .fw:first-child input { height: auto; padding: 6px 9px; border-radius: 6px; border: 1px solid rgba(148,163,184,.2); background: rgba(148,163,184,.06); font-size: calc(12px * var(--fs)); }
  #kb .filters > .fw:first-child input:focus { border-color: #a78bfa; }
  #nav.folded ~ #kb .filters > .fw:first-child { opacity: 0; visibility: hidden; pointer-events: none; transition: opacity .2s, visibility 0s .2s; }
  body.kanban #nav section.note { margin-top: calc(var(--nv-sh, 29px) + 18px); }
  /* folded: a magnifier in the strip at the search's height unfolds the panel and focuses the search; lit while a query is set */
  #nv-mag { all: unset; box-sizing: border-box; position: fixed; z-index: 4; left: 13px; top: var(--nv-sy, 166px); width: 26px; height: 26px; display: grid; place-items: center; cursor: pointer;
    border-radius: 6px; color: #94a3b8; opacity: 0; visibility: hidden; transition: opacity .2s, visibility 0s .2s; }
  #nv-mag:hover, #nv-mag:focus-visible { color: var(--ink); background: rgba(148,163,184,.08); }
  #nv-mag.set { color: #c4b5fd; }
  #nv-mag.set::after { content: ""; position: absolute; top: 3px; right: 3px; width: 6px; height: 6px; border-radius: 50%; background: #a78bfa; box-shadow: 0 0 8px #a78bfa; }
  html.nv-fold #nv-mag { opacity: 1; visibility: visible; transition: opacity .2s .1s, visibility 0s; }
  /* the mockup's own switcher, outside the page's design */
  #nv-sw { position: fixed; z-index: 50; bottom: 10px; left: 50%; transform: translateX(-50%); display: flex; gap: 10px; align-items: center; padding: 6px 10px; border-radius: 8px;
    background: rgba(15,20,34,.92); border: 1px dashed rgba(167,139,250,.45); font: 11px Inter, system-ui, sans-serif; color: #94a3b8; white-space: nowrap; }
  #nv-sw b { font-weight: 500; color: #c4b5fd; letter-spacing: .08em; }
  #nv-sw button, #nv-sw select { all: unset; cursor: pointer; padding: 2px 7px; border-radius: 4px; border: 1px solid rgba(148,163,184,.22); color: #cbd5e1; }
  #nv-sw button.on { border-color: #a78bfa; background: rgba(167,139,250,.18); color: #fff; }
  #nv-sw select { padding-right: 16px; }
  #nv-sw .grp { display: flex; gap: 4px; align-items: center; }
  #nv-sw.min .grp { display: none; }
  #nv-sw b { cursor: pointer; }
  html.nv-nochrome #nv-sw { display: none; }
  `;

  const setValue = (input, v) => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    set.call(input, v);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const searchInput = () => document.querySelector("#q") || document.querySelector("#kb .filters > .fw:first-child input");

  function addX(input) {
    const host = input.parentElement;
    let x = host.querySelector(":scope > .nv-x");
    if (!x) {
      x = document.createElement("button");
      x.className = "nv-x";
      x.type = "button";
      x.textContent = "✕";
      x.title = "Clear the search";
      x.setAttribute("aria-label", "Clear the search");
      x.addEventListener("mousedown", (e) => e.preventDefault());
      x.addEventListener("click", () => { setValue(input, ""); input.focus(); });
      host.appendChild(x);
    }
    x.classList.toggle("on", input.value !== "");
  }

  function sync() {
    const root = document.documentElement;
    const nav = document.querySelector("#nav");
    if (!nav) return;
    // the icon sits inside the glyph element React renders empty, so React never touches it
    const g = nav.querySelector("section.views:not(.admin-sec) .node:first-of-type > i.g");
    if (g && g.dataset.nv !== icon) { g.innerHTML = SVG[icon] || ""; g.dataset.nv = icon; }
    // the search slot: where the Star Map search sits, just under the Views
    const views = nav.querySelector("section.views");
    if (views) {
      const y = views.getBoundingClientRect().bottom + 18;
      root.style.setProperty("--nv-sy", y + "px");
      const inp = searchInput();
      if (inp) root.style.setProperty("--nv-sh", inp.getBoundingClientRect().height + "px");
    }
    root.classList.toggle("nv-fold", nav.classList.contains("folded"));
    for (const inp of document.querySelectorAll("#q, #kb .filters > .fw:first-child input")) addX(inp);
    const mag = document.querySelector("#nv-mag");
    const inp = searchInput();
    if (mag) {
      mag.classList.toggle("set", !!(inp && inp.value));
      const view = document.body.classList.contains("kanban") ? "Kanban" : "Star Map";
      mag.title = `Search the ${view}${inp && inp.value ? ` (filtering: ${inp.value})` : ""}`;
    }
  }

  function switcher() {
    const sw = document.createElement("div");
    sw.id = "nv-sw";
    const go = (o) => {
      const p = new URLSearchParams(location.search);
      p.set("s", o.s ?? sKey ?? (document.body.classList.contains("kanban") ? "kanban" : "map"));
      p.set("icon", icon);
      p.set("fs", String(o.fs ?? fs ?? 100));
      if (qs.get("chrome")) p.set("chrome", qs.get("chrome"));
      p.delete("view");
      try { sessionStorage.setItem("nv.next", p.toString()); } catch {}
      try { history.replaceState(null, "", location.pathname + "?" + p.toString()); } catch {}
      location.reload();
    };
    const iconGrp = ICONS.map((k) => `<button data-icon="${k}" class="${k === icon ? "on" : ""}">${{ constellation: "Constellation", compass: "Compass", orbit: "Orbit", chart: "Star chart", sextant: "Map + sextant", current: "Today's ring" }[k]}</button>`).join("");
    const sizeGrp = SIZES.map((n) => `<button data-fs="${n}" class="${n === (fs ?? 100) ? "on" : ""}">${n}%</button>`).join("");
    const opts = Object.keys(STATES).map((k) => `<option value="${k}" ${k === sKey ? "selected" : ""}>${k}</option>`).join("");
    sw.innerHTML = `<b title="Fold the mockup controls">MOCKUP ▾</b><span class="grp">icon ${iconGrp}</span><span class="grp">text ${sizeGrp}</span><span class="grp">state <select aria-label="Mockup state">${sKey ? "" : "<option>—</option>"}${opts}</select></span>`;
    sw.addEventListener("click", (e) => {
      if (e.target.closest("b")) { sw.classList.toggle("min"); return; }
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.icon) {
        icon = b.dataset.icon;
        for (const k of ICONS) document.documentElement.classList.toggle("nv-" + k, k === icon);
        for (const x of sw.querySelectorAll("[data-icon]")) x.classList.toggle("on", x === b);
        const p = new URLSearchParams(location.search);
        p.set("icon", icon);
        try { history.replaceState(null, "", location.pathname + "?" + p.toString()); } catch {}
        sync();
      }
      if (b.dataset.fs) go({ fs: +b.dataset.fs });
    });
    sw.querySelector("select").addEventListener("change", (e) => go({ s: e.target.value }));
    document.body.appendChild(sw);
  }

  function boot() {
    const style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);
    const mag = document.createElement("button");
    mag.id = "nv-mag";
    mag.type = "button";
    mag.setAttribute("aria-label", "Search");
    mag.innerHTML = MAG;
    mag.addEventListener("click", () => {
      const nav = document.querySelector("#nav");
      if (nav && nav.classList.contains("folded")) document.querySelector("#fold")?.click();
      setTimeout(() => searchInput()?.focus(), 320);
    });
    document.body.appendChild(mag);
    switcher();
    new MutationObserver(sync).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["class"] });
    document.addEventListener("input", sync, true);
    addEventListener("resize", sync);
    setInterval(sync, 250);
    // a linked state that needs typing types into the page's own input once it has drawn
    if (preset) {
      let tries = 0;
      const t = setInterval(() => {
        const inp = searchInput();
        if (!inp && ++tries < 80) return;
        clearInterval(t);
        if (!inp) return;
        if (preset.q) setValue(inp, preset.q);
        if (preset.focus) { inp.focus(); setValue(inp, inp.value); }
        sync();
      }, 100);
    }
    sync();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
