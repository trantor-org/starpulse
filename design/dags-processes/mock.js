// Design mockup of the DAGs catalog with process packages (doc-230, Approach A), never part of the page. It draws the live
// catalog's own markup (Dags.tsx: header, filters, Fold, Census, DagRow, Orb, Strip) from data.js, adding one level: a domain
// whose config nests processes holds a process Fold per process, in table order, each with its census and count. A process
// starts open when its domain has three processes or fewer or when it holds a DAG that is not healthy; a toggle overrides
// that for the session. Flat domains (Host timers, github) keep today's one level. No Process chip; search also reads process names.
(() => {
  const q = new URLSearchParams(location.search), F = window.__DAGS_FIXTURE__;
  if (!q.has("view")) { q.set("view", "dags"); history.replaceState(null, "", `?${q}`); }
  const fs = Number(q.get("fs") || 100) / 100;
  document.documentElement.style.setProperty("--fs", String(fs));

  // One DAG mid-run, as apply-on-merge is for a few minutes after each merge: its fan is part done, apply_images running.
  const now0 = F.now, iso = (s) => new Date(s * 1000).toISOString().replace(/\.\d+Z$/, "Z");
  const aom = F.dags.find((d) => d.name === "dagu/apply-on-merge");
  if (aom) {
    const done = new Set(["validate_event", "sync", "enqueue_graph_refresh", "classify", "apply_migrations", "apply_unraid", "apply_rulesets", "apply_user_units"]);
    const st = Object.fromEntries(aom.steps.map((x) => [x.name, done.has(x.name) ? "succeeded" : x.name === "apply_images" ? "running" : "not_started"]));
    aom.status = "running";
    aom.active = [{ startedAt: iso(now0 - 94), step: "apply_images", steps: st }];
  }

  // dags.ts: phase, order, ago, took, place
  const short = (n) => n.replace(/^[^/]+\//, "");
  const group = (p) => (p === "queued" ? "running" : p);
  const PHASES = [["running", "Running"], ["failed", "Failing"], ["idle", "Not run"], ["ok", "Healthy"]];
  const RANK = { running: 0, queued: 1, failed: 2, idle: 3, ok: 4 };
  const ts = (s) => (s ? Date.parse(s) / 1000 : 0);
  const home = {};
  for (const dom of F.domains) {
    for (const x of dom.dags) home[x.name] = { domain: dom.name, process: "", runSafe: x.runSafe };
    for (const p of dom.processes || []) for (const x of p.dags) home[x.name].process = p.name;
  }
  const all = F.dags.map((d) => {
    const run = d.active?.[0], h = home[d.name] ?? { domain: "Other", process: "", runSafe: false };
    const phase = run || d.status === "running" ? "running" : d.status === "queued" ? "queued"
      : d.status === "failed" || d.status === "aborted" ? "failed" : d.status === "not_started" ? "idle" : "ok";
    return { d, ...h, phase, steps: Object.fromEntries(d.steps.map((x) => [x.name, run?.steps[x.name] ?? x.status])),
      startedAt: ts(run?.startedAt ?? d.startedAt), finishedAt: ts(d.finishedAt), step: run?.step ?? "" };
  });
  const order = (a, b) => RANK[a.phase] - RANK[b.phase] || b.finishedAt - a.finishedAt || a.d.name.localeCompare(b.d.name);
  const ago = (now, t) => { const s = Math.max(0, now - t); return s < 45 ? "just now" : s < 3600 ? `${Math.round(s / 60)}m ago` : s < 172800 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`; };
  const took = (a, b) => { const s = Math.max(0, Math.round(b - a)); return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`; };
  function place(steps, w, h, pad, rows, sub, gap, gy) {
    const by = Object.fromEntries(steps.map((x) => [x.name, x])), depth = {};
    const dep = (n, seen = new Set()) => {
      if (n in depth) return depth[n];
      if (seen.has(n)) return 0;
      seen.add(n);
      return (depth[n] = Math.max(0, ...(by[n]?.depends ?? []).filter((p) => by[p]).map((p) => dep(p, seen) + 1)));
    };
    steps.forEach((x) => dep(x.name));
    const cols = [];
    for (const x of steps) (cols[depth[x.name]] ??= []).push(x.name);
    const span = cols.map((c) => (Math.ceil(c.length / rows) - 1) * sub);
    const floor = cols.slice(1).map(() => sub);
    const extra = Math.max(0, w - 2 * pad - span.reduce((a, b) => a + b, 0) - floor.reduce((a, b) => a + b, 0)) / Math.max(1, floor.length);
    const gx = floor.map((f) => f + Math.min(extra, Math.max(0, gap - f)));
    const at = {};
    let x0 = pad;
    cols.forEach((c, d) => {
      c.forEach((name, i) => (at[name] = { x: x0 + Math.floor(i / rows) * sub, y: h / 2 + ((i % rows) - (Math.min(rows, c.length - Math.floor(i / rows) * rows) - 1) / 2) * gy }));
      x0 += span[d] + (gx[d] ?? 0);
    });
    return { at, wide: Math.max(1, ...cols.map((c) => Math.min(rows, c.length))) };
  }

  // DagParts.tsx, in the palette's tokens (draw.ts DAG_COLOR spells the same hues as hex; queued has no token and borrows --ready)
  const COLOR = { running: "--run", queued: "--ready", succeeded: "--ok", failed: "--fail", aborted: "--slate", skipped: "--dim", not_started: "--track" };
  const col = (s) => `var(${COLOR[s] ?? "--slate"})`;
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const star = (x, y, r, s) => {
    const c = col(s), idle = s === "not_started";
    return `<g class="step s-${s}"><circle cx="${x}" cy="${y}" r="${r}" style="fill:var(--bg0);stroke:${c}" stroke-opacity="${idle ? 0.45 : 0.85}" stroke-width="1" class="ring"/>`
      + `<circle cx="${x}" cy="${y}" r="${r * 0.34}" style="fill:${c}" fill-opacity="${idle ? 0.45 : 0.9}" class="core"/></g>`;
  };
  const PHASE_STATUS = { running: "running", queued: "queued", ok: "succeeded", failed: "failed", idle: "not_started" };
  const orb = (p) => `<i class="orb o-${p}" aria-hidden="true"><svg viewBox="-6 -6 12 12">${star(0, 0, 5, PHASE_STATUS[p])}</svg></i>`;
  let uid = 0;
  function strip(r, w = 220, h = 20) {
    const st = r.d.steps, p = place(st, w, h, 7, 3, 8, 34, Math.min(7, (h - 6) / 2));
    const rr = st.length > 9 || p.wide > 1 ? 3 : 4, at = (n) => r.steps[n] ?? "not_started", id = `u${uid++}`;
    let out = "";
    for (const s of st) for (const d of s.depends.filter((x) => p.at[x])) {
      const a = p.at[d], b = p.at[s.name], from = at(d), to = at(s.name), hot = from === "running" || to === "running", dx = (b.x - a.x) / 2, x0 = a.x + rr, x1 = b.x - rr;
      const gid = `${id}-${d}-${s.name}`.replace(/[^\w-]/g, "_");
      out += `<linearGradient id="${gid}" gradientUnits="userSpaceOnUse" x1="${x0}" y1="${a.y}" x2="${x1}" y2="${b.y}"><stop offset="0" style="stop-color:${col(from)}"/><stop offset="1" style="stop-color:${col(to)}"/></linearGradient>`
        + `<path d="M${x0} ${a.y}C${a.x + dx} ${a.y} ${b.x - dx} ${b.y} ${x1} ${b.y}" fill="none" stroke="url(#${gid})" stroke-opacity="${hot ? 0.8 : 0.42}" stroke-width="${hot ? 1.9 : 1}" stroke-dasharray="1.8 4.2" class="${hot ? "link hot" : "link"}"/>`;
    }
    for (const s of st) {
      const v = at(s.name), { x, y } = p.at[s.name];
      out += `<g class="sd s-${v}">${star(x, y, rr, v)}${s.kind === "agent" ? `<circle cx="${x}" cy="${y}" r="${rr + 2.5}" fill="none" style="stroke:var(--agent)" stroke-width="0.7"/>` : ""}</g>`;
    }
    if (st.length === 1) {
      const n = (w - 22) / (6.1 * fs * 0.88), t = st[0].name;
      out += `<text x="16" y="${h / 2 + 3.5}" class="one">${esc(t.length <= n ? t : `${t.slice(0, Math.max(1, Math.floor(n) - 1))}…`)}</text>`;
    }
    return `<svg class="dstrip" width="100%" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMinYMid meet" aria-hidden="true">${out}</svg>`;
  }
  function lastLine(r, now) {
    if (r.phase === "running") return `<b class="hot">${esc(r.step || "starting")}</b>${r.startedAt ? ` · ${took(r.startedAt, now)}` : ""}`;
    if (r.phase === "queued") return `<b class="q">queued</b>`;
    if (r.phase === "idle") return "never run";
    if (r.phase === "failed") {
      const fat = Object.entries(r.steps).find(([, v]) => v === "failed" || v === "aborted")?.[0];
      return `<span class="bad">${r.d.status === "aborted" ? "aborted" : "failed"}${fat ? ` at ${esc(fat)}` : ""}</span>${r.finishedAt ? ` · ${ago(now, r.finishedAt)}` : ""}`;
    }
    return r.finishedAt ? `${ago(now, r.finishedAt)}${r.startedAt ? ` · ${took(r.startedAt, r.finishedAt)}` : ""}` : "ran";
  }
  const poolText = (r) => { const p = F.pools.find((x) => x.name === r.d.pool); return p ? `${short(p.name)} ${p.running}/${p.cap}${p.queued ? ` +${p.queued}` : ""}` : ""; };
  const census = (rs) => `<span class="census">${PHASES.filter(([p]) => p !== "ok").map(([p, l]) => {
    const n = rs.filter((r) => group(r.phase) === p).length;
    return n ? `<span title="${n} ${l.toLowerCase()}">${orb(p)}${n}</span>` : "";
  }).join("")}</span>`;
  const why = (r) => (r.phase === "running" ? "Already running" : r.phase === "queued" ? "Already queued" : null);
  const row = (r, now) => `<div class="viewport-row"><div class="trow p-${r.phase}${r.runSafe ? " startable" : ""}" data-dag="${esc(r.d.name)}" tabindex="0">`
    + `${orb(r.phase)}<span class="nm" title="${esc(r.d.name)}">${esc(short(r.d.name))}</span>${strip(r)}<span class="last">${lastLine(r, now)}</span>`
    + `<span class="pool">${esc(poolText(r) || "—")}</span><span><span class="none">—</span></span>`
    + (r.runSafe ? `<button class="play edge"${why(r) ? " disabled" : ""} title="${esc(why(r) ?? `Run ${short(r.d.name)} now`)}" aria-label="Run ${esc(short(r.d.name))} now">▶</button>` : "<span></span>")
    + "</div></div>";

  // State: the filters, the session's fold toggles and the server clock counted on
  const S = { q: "", only: null, dom: null, menu: null, now: now0, toast: null };
  const toggled = new Map();
  const preset = q.get("s") || "smart";
  if (preset === "search") S.q = "hygiene";
  if (preset === "failing") S.only = "failed";
  if (preset === "domain") S.dom = "Delivery & CI";
  const procs = Object.fromEntries(F.domains.map((d) => [d.name, d.processes || []]));
  /** doc-230's smart open: open when the domain has three processes or fewer, or when the process holds a DAG that is not healthy. */
  const smart = (dom, proc) => procs[dom].length <= 3 || all.some((r) => r.domain === dom && r.process === proc && r.phase !== "ok");
  const isOpen = (k, dflt) => (toggled.has(k) ? toggled.get(k) : preset === "open" ? true : dflt);
  const match = (r, needle) => !needle || [r.d.name, r.domain, r.process].some((t) => t.toLowerCase().includes(needle)) || r.d.steps.some((x) => x.name.toLowerCase().includes(needle));
  const filtered = () => { const n = S.q.trim().toLowerCase(); return all.filter((r) => (!S.only || group(r.phase) === S.only) && (!S.dom || r.domain === S.dom) && match(r, n)); };

  const fold = (k, title, n, open, body, cls = "") => `<div class="bucket${cls}${open ? "" : " folded"}" data-k="${esc(k)}"><div class="bh" role="button" tabindex="0" aria-expanded="${open}">`
    + `<span class="tw">▾</span><span class="bn">${title}</span><span class="c">${n}</span></div>${open ? body : ""}</div>`;
  const plural = (n, one) => `${n} ${one}${n === 1 ? "" : "s"}`;
  const chip = (name, label, text) => `<span class="fchip${text !== null ? " set" : ""}" data-chip="${name}" role="button" tabindex="0" aria-haspopup="menu" aria-expanded="${S.menu === name}">`
    + `${label}${text !== null ? `: <b>${esc(text)}</b>` : ""} ▾</span>`;
  const menu = (title, opts, value) => `<div class="scrim"></div><div class="menu" role="menu"><div class="hd">${title}</div>${opts.map(([v, l, c]) =>
    `<button role="menuitemradio" data-v="${esc(v)}" aria-checked="${v === value}"${v === value ? ' class="on"' : ""}>${esc(l)}<span>${c}</span></button>`).join("")}</div>`;

  const main = document.getElementById("dg");
  function draw() {
    const scroll = main.querySelector("#catalog")?.scrollTop ?? 0, focus = document.activeElement?.closest?.("[data-k]")?.dataset.k;
    const rs = filtered(), now = S.now;
    const doms = F.domains.map((d) => d.name).concat(rs.some((r) => r.domain === "Other") ? ["Other"] : []).filter((d) => rs.some((r) => r.domain === d));
    let cat = `<div class="thead"><span></span><span>DAG</span><span>Steps</span><span>Last run</span><span>Pool</span><span>Board</span><span></span></div>`;
    for (const d of doms) {
      const list = rs.filter((r) => r.domain === d).sort(order), ps = procs[d] ?? [];
      let body;
      if (ps.length) {
        const names = ps.map((p) => p.name).concat(list.some((r) => !r.process) ? ["Other"] : []);
        body = names.map((p) => {
          const pl = list.filter((r) => (r.process || "Other") === p);
          if (!pl.length) return "";
          const k = `cat|${d}|${p}`;
          return fold(k, `${esc(p)} ${census(pl)}`, pl.length, isOpen(k, smart(d, p)), pl.map((r) => row(r, now)).join(""), " process");
        }).join("");
      } else body = list.map((r) => row(r, now)).join("");
      const k = `cat|${d}`;
      cat += fold(k, `${esc(d)} ${census(list)}`, list.length, isOpen(k, true), body);
    }
    const domOpts = [...new Set(all.map((r) => r.domain))].map((d) => [d, d, all.filter((r) => r.domain === d).length]);
    main.innerHTML = `<header><span class="title">DAGs</span><span class="count">${plural(all.length, "DAG")} · ${plural(new Set(all.map((r) => r.domain)).size, "domain")}</span>`
      + `<span class="sky">${census(all)}</span></header>`
      + `<div class="filters"><div class="fw"><input id="dgq" type="text" placeholder="filter by name, step, process or domain…" aria-label="Filter DAGs by name, step, process or domain" autocomplete="off" spellcheck="false" value="${esc(S.q)}"></div>`
      + `<div class="fw">${chip("status", "Status", S.only && PHASES.find(([p]) => p === S.only)[1])}${S.menu === "status" ? menu("Status", PHASES.map(([p, l]) => [p, l, all.filter((r) => group(r.phase) === p).length]), S.only) : ""}</div>`
      + `<div class="fw">${chip("domain", "Domain", S.dom)}${S.menu === "domain" ? menu("Domain", domOpts, S.dom) : ""}</div>`
      + `<div class="fw">${chip("recency", "Last run", null)}</div>`
      + `${S.only || S.dom || S.q ? '<button class="clear">clear</button>' : ""}`
      + `<span class="shown">${rs.length === all.length ? `${all.length} shown` : `${rs.length} of ${all.length} shown`}</span></div>`
      + (rs.length ? `<div id="catalog">${cat}</div>` : `<div class="none">No DAG matches the filters.</div>`)
      + (S.toast ? `<div class="dtoast" role="status">${esc(S.toast)}</div>` : "");
    const c = main.querySelector("#catalog");
    if (c) {
      c.scrollTop = scroll;
      const th = c.querySelector(".thead"), bh = c.querySelector(".bucket:not(.process) > .bh");
      c.style.setProperty("--headh", `${th.offsetHeight}px`);
      if (bh) c.style.setProperty("--subtop", `${th.offsetHeight + bh.offsetHeight}px`);
    }
    if (focus) main.querySelector(`[data-k="${CSS.escape(focus)}"] > .bh`)?.focus();
  }

  let toastT;
  const toast = (t) => { S.toast = t; clearTimeout(toastT); toastT = setTimeout(() => { S.toast = null; draw(); }, 4000); draw(); };
  const flip = (k) => { const b = main.querySelector(`[data-k="${CSS.escape(k)}"]`); toggled.set(k, b.classList.contains("folded")); draw(); };
  main.addEventListener("click", (e) => {
    const t = e.target;
    const bh = t.closest(".bh");
    if (bh) return flip(bh.parentElement.dataset.k);
    const ch = t.closest(".fchip");
    if (ch) { const n = ch.dataset.chip; S.menu = n === "recency" ? null : S.menu === n ? null : n; return draw(); }
    if (t.closest(".scrim")) { S.menu = null; return draw(); }
    const mi = t.closest(".menu button");
    if (mi) { const v = mi.dataset.v; if (S.menu === "status") S.only = S.only === v ? null : v; else S.dom = S.dom === v ? null : v; S.menu = null; return draw(); }
    if (t.closest(".clear")) { S.q = ""; S.only = null; S.dom = null; return draw(); }
    const play = t.closest(".play.edge");
    if (play) { e.stopPropagation(); return toast(`${short(play.closest(".trow").dataset.dag)}: started (mockup: no run is sent)`); }
    const tr = t.closest(".trow");
    if (tr) toast(`${short(tr.dataset.dag)}: its modal opens here, unchanged by this design`);
  });
  main.addEventListener("keydown", (e) => {
    const bh = e.target.closest?.(".bh");
    if (bh && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); flip(bh.parentElement.dataset.k); }
    if (e.target.id === "dgq" && e.key === "Escape") { S.q = ""; draw(); main.querySelector("#dgq").focus(); }
    if (e.target.classList?.contains("trow") && e.key === "Enter") e.target.click();
  });
  main.addEventListener("input", (e) => {
    if (e.target.id !== "dgq") return;
    S.q = e.target.value;
    const pos = e.target.selectionStart;
    draw();
    const inp = main.querySelector("#dgq");
    inp.focus();
    inp.setSelectionRange(pos, pos);
  });
  setInterval(() => { S.now += 1; if (all.some((r) => r.phase === "running")) for (const el of main.querySelectorAll(".trow.p-running .last")) {
    const r = all.find((x) => x.d.name === el.parentElement.dataset.dag); el.innerHTML = lastLine(r, S.now);
  } }, 1000);
  draw();

  // The review bar: each starting state and text size, each a link to its own address.
  const bar = document.createElement("div");
  bar.id = "mockbar";
  bar.innerHTML = "<b>MOCKUP</b>";
  const cur = { s: preset, fs: q.get("fs") || "100" };
  const groups = [
    ["State", "s", [["smart", "Smart open"], ["open", "All open"], ["search", "Search “hygiene”"], ["failing", "Status: Failing"], ["domain", "Domain: Delivery & CI"]]],
    ["Text", "fs", [["100", "100%"], ["125", "125%"], ["150", "150%"]]],
  ];
  for (const [title, key, opts] of groups) {
    const g = document.createElement("span");
    g.append(title);
    for (const [v, l] of opts) {
      const a = document.createElement("a"), u = new URLSearchParams(location.search);
      if (v === (key === "s" ? "smart" : "100")) u.delete(key);
      else u.set(key, v);
      a.href = `?${u}`;
      a.textContent = l;
      if (cur[key] === v) a.className = "on";
      g.append(a);
    }
    bar.append(g);
  }
  document.body.append(bar);
})();
