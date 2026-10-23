// Design mockup layer (state-type display), never part of the page. The page above is the branch's real page, built with
// column-labels-src.patch, over the PR demo's capture. Each column keeps the machine's name and order; its header carries a glyph
// for the state's declared type, named on hover. This bar picks the view (?view=kanban|constellation) and the text size
// (?fs=100|125|150); ?bar=0 hides it.
(() => {
  const q = new URLSearchParams(location.search);
  if (!q.has("view")) { q.set("view", "kanban"); history.replaceState(null, "", `?${q}`); }
  try {
    const k = "fv.admin.prefs", p = JSON.parse(localStorage.getItem(k) || "{}");
    p.scale = Number(q.get("fs") || 100);
    localStorage.setItem(k, JSON.stringify(p));
  } catch { /* storage off: the page keeps 100% */ }

  // The review bar: each choice a link to its own address.
  const bar = document.createElement("div");
  bar.id = "mockbar";
  bar.innerHTML = `<style>
    #mockbar { position: fixed; z-index: 50; bottom: 12px; left: 50%; transform: translateX(-50%); display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; justify-content: center;
      width: max-content; max-width: min(900px, calc(100vw - 24px)); box-sizing: border-box; padding: 6px 10px; border-radius: 9px; border: 1px dashed rgba(251,191,36,.45); background: rgba(10,12,20,.92);
      font: 11px Inter, system-ui, sans-serif; color: #6b7a93; }
    @media (max-width: 900px) { #mockbar { bottom: auto; top: 6px; max-width: calc(100vw - 16px); } }
    #mockbar b { color: #fbbf24; font-weight: 500; letter-spacing: .2em; font-size: 9.5px; }
    #mockbar span { display: inline-flex; flex-wrap: wrap; gap: 3px; align-items: center; }
    #mockbar a { all: unset; cursor: pointer; padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(148,163,184,.18); color: #b6c0d3; text-decoration: none; }
    #mockbar a.on { border-color: #fbbf24; color: #fde68a; background: rgba(251,191,36,.10); }
    #mockbar i { flex-basis: 100%; text-align: center; font-style: normal; color: #b6c0d3; }
  </style><b>MOCKUP</b>`;
  const cur = { view: q.get("view"), fs: q.get("fs") || "100" };
  const groups = [
    ["View", "view", [["kanban", "Kanban"], ["constellation", "Star Map"]]],
    ["Text", "fs", [["100", "100%"], ["125", "125%"], ["150", "150%"]]],
  ];
  for (const [title, k, opts] of groups) {
    const g = document.createElement("span");
    g.append(title);
    for (const [v, l] of opts) {
      const a = document.createElement("a"), u = new URLSearchParams(location.search);
      u.set(k, v);
      a.href = `?${u}`;
      a.textContent = l;
      if (cur[k] === v) a.className = "on";
      g.append(a);
    }
    bar.append(g);
  }
  const line = document.createElement("i");
  line.textContent = "each header's glyph marks its state's declared type: hover it for the type · names and order are the machine's";
  bar.append(line);

  // Once the page has drawn, show the bar.
  const start = (tries = 150) => {
    if (document.querySelector("#kb #cols section") || (q.get("view") !== "kanban" && document.querySelector("canvas"))) {
      if (q.get("bar") !== "0") document.body.append(bar);
    } else if (tries) setTimeout(() => start(tries - 1), 100);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => start());
  else start();
})();
