// Design mockup layer (the DAGs tied to a state, back on the Star Map), never part of the page. The page above is a scrubbed capture of the
// real StarPulse page, built from a source copy that draws each DAG tied to a Board state beside the transition it writes, the event that
// cues it or the machine it launches (dag-ties-src.patch). This layer adds the review bar, the text size (?fs=100|125|150) and their runs,
// simulated on a loop shaped like the live day: autopilot claims, reconciliation releases, a merge cues apply-on-merge and graph-refresh,
// the sweep, a skill eval. ?sim=live (the loop), rest (nothing running) or fail (apply-on-merge failed and unresolved until its forced rerun);
// ?at=<seconds> opens the loop at that moment.
// It runs before the page's module.
(() => {
  const q = new URLSearchParams(location.search);
  try {
    const k = "fv.admin.prefs", p = JSON.parse(localStorage.getItem(k) || "{}");
    p.scale = Number(q.get("fs") || 100);
    localStorage.setItem(k, JSON.stringify(p));
    // every link opens on the Board, whatever level the last visit ended on
    localStorage.removeItem("fv.path");
  } catch { /* storage off: the page keeps 100% and opens on the Board */ }

  // The loop, in seconds from page load: [dag, start, duration, outcome, event it writes]
  const sim = q.get("sim") || "live", P = 80;
  const plan = [
    ["dagu/board-autopilot", 4, 6, "ok", "CLAIM"],
    ["dagu/main-follow", 14, 3, "ok", "MERGED"],
    ["dagu/apply-on-merge", 17.5, 7, "fail"],
    ["dagu/graph-refresh", 17.5, 4, "ok"],
    ["dagu/board-dependency-reconciliation", 30, 4, "ok", "DEP_RESOLVED"],
    ["dagu/skill-eval", 38, 12, "ok"],
    ["dagu/board-autopilot", 44, 6, "ok", "DEFER"],
    ["dagu/apply-on-merge", 56, 7, "ok"], // the forced rerun that clears the failure
    ["dagu/backlog-sweep", 66, 3, "ok", "SWEEP"],
  ];
  // ?at=<seconds> opens the loop that far in (a merge lands at 17, the skill eval launches at 38); a failure opens just after apply-on-merge fails
  const t00 = Date.now() / 1000 - Number(q.get("at") || (sim === "fail" ? 26 : 0));
  window.__ties = {};
  if (sim === "rest") return bar();
  const tick = () => {
    const now = Date.now() / 1000, loop = Math.floor((now - t00) / P), out = {};
    // the latest run of each DAG that has started in this loop (or the last one), and a failure stays until the run that clears it
    for (let k = loop - 1; k <= loop; k++)
      for (const [dag, s, d, how, event] of plan) {
        const t0 = t00 + k * P + s, fin = t0 + d;
        if (t0 > now || k < 0) continue;
        const prev = out[dag];
        if (prev && prev.t0 > t0) continue;
        out[dag] = now < fin ? { status: "running", t0, dur: d }
          : how === "fail" ? { status: "failed", t0, dur: d, fin, unresolved: true }
          : { status: "succeeded", t0, dur: d, fin, ...(event ? { wrote: fin, event } : {}) };
      }
    window.__ties = out;
  };
  tick();
  setInterval(tick, 200);
  bar();

  // The review bar: every variant and the text size, each a link to its own address.
  function bar() {
    const mount = () => {
      const el = document.createElement("div");
      el.id = "mockbar";
      el.innerHTML = `<style>
        #mockbar { position: fixed; z-index: 50; bottom: 12px; left: 50%; transform: translateX(-50%); display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; justify-content: center;
          max-width: calc(100vw - 540px); padding: 6px 10px; border-radius: 9px; border: 1px dashed rgba(251,191,36,.45); background: rgba(10,12,20,.9); font: 11px Inter, system-ui, sans-serif; color: #6b7a93; }
        #mockbar b { color: #fbbf24; font-weight: 500; letter-spacing: .2em; font-size: 9.5px; }
        #mockbar span { display: inline-flex; gap: 3px; align-items: center; }
        #mockbar a { padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(148,163,184,.18); color: #b6c0d3; text-decoration: none; }
        #mockbar a.on { border-color: #fbbf24; color: #fde68a; background: rgba(251,191,36,.10); }
      </style><b>MOCKUP</b>`;
      const cur = { place: q.get("place") || "edge", names: q.get("names") || "0", motion: q.get("motion") || "breath", sim, fs: q.get("fs") || "100" };
      const groups = [
        ["Placement", "place", [["edge", "On the edge"], ["sat", "Satellite"], ["rim", "Rim band"]]],
        ["Names", "names", [["0", "On hover"], ["1", "Always"]]],
        ["Motion", "motion", [["breath", "Breath"], ["spark", "Spark"], ["still", "Still"]]],
        ["Runs", "sim", [["live", "Live loop"], ["rest", "At rest"], ["fail", "Failure"]]],
        ["Text", "fs", [["100", "100%"], ["125", "125%"], ["150", "150%"]]],
      ];
      for (const [title, key, opts] of groups) {
        const g = document.createElement("span");
        g.append(title);
        for (const [v, l] of opts) {
          const a = document.createElement("a"), u = new URLSearchParams(location.search);
          u.set(key, v);
          a.href = `?${u}`;
          a.textContent = l;
          if (cur[key] === v) a.className = "on";
          g.append(a);
        }
        el.append(g);
      }
      document.body.append(el);
    };
    if (document.body) mount();
    else addEventListener("DOMContentLoaded", mount);
  }
})();
