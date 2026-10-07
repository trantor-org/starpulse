// Design mockup layer (DAG constellations), never part of the page. The page above is a scrubbed capture of the real
// StarPulse page built from a source copy whose only changes are the DAGs: how a DAG is drawn (?glyph=quiet|radiant|live), where a
// DAG with no Board tie sits (?free=sky|marks|live) and the navigator without its DAGS list. This layer adds the review bar, the
// text size (?fs=100|125|150, the Admin font size) and synthetic DAGs for scale (?n=150|400). It runs before the page's module.
(() => {
  const q = new URLSearchParams(location.search), F = window.__FLOW_FIXTURE__;
  try {
    const k = "fv.admin.prefs", p = JSON.parse(localStorage.getItem(k) || "{}");
    p.scale = Number(q.get("fs") || 100);
    localStorage.setItem(k, JSON.stringify(p));
  } catch { /* storage off: the page keeps 100% */ }

  // Synthetic DAGs, shaped like the live ones: about two in three are one step, the rest short chains or fans.
  const n = Number(q.get("n") || 0);
  if (F && n > F.dags.length) {
    let seed = 7;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const pick = (a) => a[Math.floor(rnd() * a.length)];
    const extra = ["Data pipelines", "Security scans", "Media library", "Home automation", "Reports", "Network", "Backups offsite", "Model training", "Docs site"];
    const doms = F.domains.map((d) => d.name).concat(extra.slice(0, n > 200 ? 9 : 3));
    const verbs = ["sync", "sweep", "audit", "rotate", "export", "index", "prune", "verify", "report", "rebuild", "scan", "refresh", "reconcile", "archive", "probe"];
    const nouns = ["photos", "certs", "metrics", "logs", "tags", "images", "secrets", "feeds", "tables", "volumes", "dns", "mirrors", "reviews", "alerts", "notes", "vectors"];
    const steps = ["fetch", "check", "apply", "verify", "notify", "plan", "build", "push", "diff", "report"];
    const used = new Set(F.dags.map((d) => d.name));
    for (let i = F.dags.length; i < n; i++) {
      let name = `dagu/${pick(verbs)}-${pick(nouns)}`;
      for (let k = 2; used.has(name); k++) name = `dagu/${pick(verbs)}-${pick(nouns)}-${k}`;
      used.add(name);
      const r = rnd(), len = r < 0.66 ? 1 : 2 + Math.floor(rnd() * 6), fanOut = rnd() < 0.35;
      const status = rnd() < 0.04 ? "failed" : rnd() < 0.1 ? "not_started" : "succeeded";
      const ss = Array.from({ length: len }, (_, j) => ({ name: `${steps[j % steps.length]}${j >= steps.length ? j : ""}`, kind: "code", status,
        depends: j === 0 ? [] : [fanOut && j > 1 ? steps[0] : `${steps[(j - 1) % steps.length]}${j - 1 >= steps.length ? j - 1 : ""}`] }));
      F.dags.push({ name, status, runId: "", startedAt: "", finishedAt: "", steps: ss, active: [], pool: "default" });
      const dn = doms[Math.floor(rnd() * doms.length)];
      let d = F.domains.find((x) => x.name === dn);
      if (!d) F.domains.push((d = { name: dn, dags: [] }));
      d.dags.push({ name, runSafe: false });
    }
  }

  // The review bar: every variant, the scale and the text size, each a link to its own address.
  const bar = document.createElement("div");
  bar.id = "mockbar";
  bar.innerHTML = `<style>
    #mockbar { position: fixed; z-index: 50; bottom: 12px; left: 50%; transform: translateX(-50%); display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; justify-content: center;
      max-width: calc(100vw - 560px); padding: 6px 10px; border-radius: 9px; border: 1px dashed rgba(251,191,36,.45); background: rgba(10,12,20,.9); font: 11px Inter, system-ui, sans-serif; color: #6b7a93; }
    #mockbar b { color: #fbbf24; font-weight: 500; letter-spacing: .2em; font-size: 9.5px; }
    #mockbar span { display: inline-flex; gap: 3px; align-items: center; }
    #mockbar a { padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(148,163,184,.18); color: #b6c0d3; text-decoration: none; }
    #mockbar a.on { border-color: #fbbf24; color: #fde68a; background: rgba(251,191,36,.10); }
  </style><b>MOCKUP</b>`;
  const cur = { glyph: q.get("glyph") || "quiet", free: q.get("free") || "sky", n: q.get("n") || "", fs: q.get("fs") || "100" };
  const groups = [
    ["Glyph", "glyph", [["quiet", "Quiet"], ["radiant", "Radiant"], ["live", "Today"]]],
    ["Free DAGs", "free", [["sky", "Sky"], ["marks", "Marks"], ["live", "Today's hangar"]]],
    ["DAGs", "n", [["", "Live"], ["150", "150"], ["400", "400"]]],
    ["Text", "fs", [["100", "100%"], ["125", "125%"], ["150", "150%"]]],
  ];
  for (const [title, key, opts] of groups) {
    const g = document.createElement("span");
    g.append(title);
    for (const [v, l] of opts) {
      const a = document.createElement("a"), u = new URLSearchParams(location.search);
      if (v) u.set(key, v);
      else u.delete(key);
      a.href = `?${u}`;
      a.textContent = l;
      if (cur[key] === v) a.className = "on";
      g.append(a);
    }
    bar.append(g);
  }
  document.body.append(bar);
})();
