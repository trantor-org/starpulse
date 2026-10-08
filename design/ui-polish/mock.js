// Design mockup layer (the Kanban, DAGs and start-question UI polish), never part of the page. The page above is the branch's real page over the PR demo's
// capture. This layer adds the review bar, the harnesses the start question offers (?harness=two|one|none; a demo page has none),
// a start that the session-start service accepts, a stack held open (?s=stack) or the start question asked (?s=start) on load,
// and the text size (?fs=100|125|150). It runs before the page's module.
(() => {
  const q = new URLSearchParams(location.search);
  if (!q.has("view")) { q.set("view", "kanban"); history.replaceState(null, "", `?${q}`); }
  try {
    const k = "fv.admin.prefs", p = JSON.parse(localStorage.getItem(k) || "{}");
    p.scale = Number(q.get("fs") || 100);
    localStorage.setItem(k, JSON.stringify(p));
  } catch { /* storage off: the page keeps 100% */ }

  // The live server's /api/harnesses, and a second harness for the Harness picker; ?harness=none is a server that names none.
  const claude = { name: "claude", label: "Claude Code", sessions: true, reason: null,
    tiers: { fast: { model: "haiku", efforts: [] }, standard: { model: "sonnet", efforts: ["medium", "high"] }, deep: { model: "opus", efforts: ["medium", "high"] } } };
  const codex = { name: "codex", label: "Codex", sessions: true, reason: null,
    tiers: { standard: { model: "gpt-5", efforts: ["low", "medium", "high"] }, deep: { model: "gpt-5-pro", efforts: ["high"] } } };
  const set = { two: [claude, codex], one: [claude], none: [] }[q.get("harness") || "two"] || [claude, codex];
  window.__MOCK_API__ = {
    "/api/harnesses": () => (set.length ? [{ tiers: ["fast", "standard", "deep"], harnesses: set }, 200] : [{ error: "no harness configured" }, 503]),
    "/api/start": () => [{ url: "#session", at: Date.now() / 1000 }, 200],
  };

  // A starting state, once the board has drawn: a Waiting stack held open, or the start question on the first startable card.
  const s = q.get("s");
  if (s) {
    const until = (find, act, tries = 80) => {
      const el = find();
      if (el) act(el);
      else if (tries) setTimeout(() => until(find, act, tries - 1), 100);
    };
    if (s === "stack") until(() => document.querySelector(".stack .card"), (el) => el.focus());
    if (s === "start") until(() => document.querySelector(".card.startable button.play:not(:disabled)"), (el) => setTimeout(() => el.click(), 300));
  }

  // The review bar: every variant, each a link to its own address.
  const bar = document.createElement("div");
  bar.id = "mockbar";
  bar.innerHTML = `<style>
    #mockbar { position: fixed; z-index: 50; bottom: 12px; left: 50%; transform: translateX(-50%); display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; justify-content: center;
      max-width: calc(100vw - 540px); padding: 6px 10px; border-radius: 9px; border: 1px dashed rgba(251,191,36,.45); background: rgba(10,12,20,.9); font: 11px Inter, system-ui, sans-serif; color: #6b7a93; }
    #mockbar b { color: #fbbf24; font-weight: 500; letter-spacing: .2em; font-size: 9.5px; }
    #mockbar span { display: inline-flex; gap: 3px; align-items: center; }
    #mockbar a { padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(148,163,184,.18); color: #b6c0d3; text-decoration: none; }
    #mockbar a.on { border-color: #fbbf24; color: #fde68a; background: rgba(251,191,36,.10); }
  </style><b>MOCKUP</b>`;
  const cur = { view: q.get("view"), s: q.get("s") || "", harness: q.get("harness") || "two", fs: q.get("fs") || "100" };
  const groups = [
    ["View", "view", [["kanban", "Kanban"], ["dags", "DAGs"], ["constellation", "Star Map"]]],
    ["Open", "s", [["", "Nothing"], ["stack", "Stack"], ["start", "Start question"]]],
    ["Harnesses", "harness", [["two", "Two"], ["one", "One"], ["none", "None"]]],
    ["Text", "fs", [["100", "100%"], ["125", "125%"], ["150", "150%"]]],
  ];
  for (const [title, key, opts] of groups) {
    const g = document.createElement("span");
    g.append(title);
    for (const [v, l] of opts) {
      const a = document.createElement("a"), u = new URLSearchParams(location.search);
      if (v) u.set(key, v);
      else u.delete(key);
      // the stack and the start question are on the Kanban
      if (key === "s" && v) u.set("view", "kanban");
      a.href = `?${u}`;
      a.textContent = l;
      if (cur[key] === v) a.className = "on";
      g.append(a);
    }
    bar.append(g);
  }
  document.addEventListener("DOMContentLoaded", () => document.body.append(bar));
  if (document.body) document.body.append(bar);
})();
