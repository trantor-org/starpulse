// Mockup layer: the two-column Kanban task modal and the collapsible Connect a tracker modal, injected over a
// scrubbed capture of the live page. A click on a card, a Held-by chip or Connect a tracker opens this layer's
// modal instead of the page's own. Everything only the task file or a not-yet-built backend holds (the record's
// criteria and plan, Start Criteria results, CI history) is synthesized per task, deterministically.
(() => {
  const qs = new URLSearchParams(location.search);
  const STATES = {
    kanban: {},
    review: { open: (t) => pick(t, (a) => a.state === "review" && pulls(a.id).length > 1 && a.dependencies.length) },
    "in-progress": { open: (t) => pick(t, (a) => a.state === "in_progress" && machinesOf(a.id).length > 2) },
    "start-criteria": { open: (t) => pick(t, (a) => a.state === "waiting" && !a.dependencies.length) },
    "waiting-deps": { open: (t) => pick(t, (a) => a.state === "waiting" && a.dependencies.length > 2) },
    ready: { open: (t) => pick(t, (a) => a.state === "ready" && !a.dependencies.length) },
    long: { open: (t) => pick(t, (a) => a.state === "in_progress" && pulls(a.id).length > 1), long: true },
    edit: { open: (t) => pick(t, (a) => a.state === "review" && pulls(a.id).length > 1 && a.dependencies.length), edit: "desc" },
    "edit-ac": { open: (t) => pick(t, (a) => a.state === "review" && pulls(a.id).length > 1 && a.dependencies.length), edit: "ac" },
    tracker: { tracker: true },
    "tracker-open": { tracker: true, expand: ["jira"] },
    "tracker-hint": { tracker: true, hint: true },
  };
  const preset = STATES[qs.get("s")] || null;
  const SCROLLS = ["split", "shared", "fold"];
  const SIZES = ["100", "125", "150"];
  let scroll = SCROLLS.includes(qs.get("scroll")) ? qs.get("scroll") : "split";
  let size = SIZES.includes(qs.get("fs")) ? qs.get("fs") : "100";
  const bare = qs.has("bare");
  {
    // the page itself opens the Kanban; its own ?task= deep link would open the old modal, so this layer takes it
    const p = new URLSearchParams(location.search);
    p.set("view", "kanban");
    p.delete("task");
    try { history.replaceState(null, "", location.pathname + "?" + p.toString() + location.hash); } catch {}
  }

  // ---- data: the snapshot's entry plus what the task file and the backend would hold ----
  const fx = () => window.__FLOW_FIXTURE__ || {};
  const board = () => (fx().flows || [])[0]?.agents || [];
  const byId = (id) => board().find((a) => a.id === id);
  const pulls = (id) => (fx().pulls || {})[id] || [];
  const num = (id) => +String(id).replace(/\D/g, "") || 1;
  const nowS = () => fx().now || Date.now() / 1000;
  function pick(_, test) { return board().find(test)?.id || board()[0]?.id; }
  function machinesOf(id) {
    const out = [];
    for (const f of (fx().flows || []).slice(1)) for (const a of f.agents || []) if (a.task === id) out.push({ machine: f.name, ...a });
    return out.sort((x, y) => (y.active || 0) - (x.active || 0));
  }
  const LANES = { new: "New", ready: "Ready", waiting: "Waiting", in_progress: "In progress", review: "Review", needs_attention: "Needs attention", done: "Done", completed: "Completed", archived: "Archived" };
  const LANE_COLOR = { ready: "#60a5fa", waiting: "#94a3b8", in_progress: "#fbbf24", review: "#a78bfa", needs_attention: "#fb7185", done: "#34d399", completed: "#34d399", archived: "#64748b" };
  const ago = (s) => (s < 90 ? `${Math.max(1, Math.round(s))}s` : s < 5400 ? `${Math.round(s / 60)}m` : s < 172800 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d`);
  const clock = (at) => new Date(at * 1000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/Phoenix" }) + " MST";
  // a time() criterion's threshold is an epoch: shown as the moment it opens
  const stamp = (at) => new Date(at * 1000).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/Phoenix" }) + " MST";
  const PRIORITIES = ["High", "Medium", "Low"];

  const CRITERIA = [
    { id: "first-remediation-ran", kind: "prom", expr: "sum(alert_remediation_attempts_total)", cmp: "at_least", want: 1, got: 0 },
    { id: "conformance-after-monday-slot", kind: "sql", expr: "SELECT count(*) FROM skill_conformance WHERE judged_at >= '2026-10-12 07:17:00+00'", cmp: "at_least", want: 1, got: 3 },
    { id: "pin-moved", kind: "file_changed_since", expr: "path: starpulse   since: 2026-10-05", cmp: "at_least", want: 1, got: 0, unit: "commits" },
    { id: "window-24h", kind: "prom", expr: "time()", cmp: "at_least", want: 1791400000, got: 1791336841, time: true, note: "24 h soak after the merge" },
  ];
  const records = new Map();
  function record(id) {
    if (records.has(id)) return records.get(id);
    const a = byId(id);
    if (!a) return null;
    const n = num(id), done = ["done", "completed", "review"].includes(a.state);
    const long = n % 5 === 3 || (preset?.long && STATES[qs.get("s")].open() === id);
    const crit = a.state === "waiting" && !a.dependencies.length
      ? [CRITERIA[n % 2], CRITERIA[2 + (n % 2)]].map((c, i) => ({ ...c, met: i === 0 ? n % 3 !== 0 : false, checked: nowS() - 600 - (n % 40) * 60 }))
      : [];
    // the demo scrub can give two pull requests one number; the mockup keeps them apart
    const pr = pulls(id).map((p, i, all) => (all.findIndex((q) => q.number === p.number) < i ? { ...p, number: p.number + 9 * i } : p));
    const r = {
      id, title: a.title, state: a.state, profile: a.model || "", priority: PRIORITIES[n % 3], milestone: a.milestone || "",
      labels: [...(a.labels || [])], dependencies: [...(a.dependencies || [])], created: a.created || nowS() - 86400 * 3,
      entered: a.entered || nowS() - 3600 * (1 + (n % 9)),
      description: describe(a, long, crit),
      criteria: crit,
      ac: [
        { n: 1, text: `${a.title} works end to end: the test that drives it fails before the change and passes after`, checked: done || n % 2 === 0 },
        { n: 2, text: "The service doc says what changed, and lint_docs.py passes on it", checked: done },
        ...(n % 3 ? [{ n: 3, text: "Operator approved the render: Kanban at 100%, 125% and 150% text size, screenshots on the PR", checked: done }] : []),
        ...(long ? [{ n: 4, text: "A refusal names the guard that refused it and the skill that clears it, in one line under the action that was refused", checked: false },
          { n: 5, text: "Nothing else on the page moves when the panel opens: the rail and the toolbar keep their positions at every text size", checked: false }] : []),
      ],
      dod: [
        { n: 1, text: "Task-specific completion outcomes are met.", checked: done },
        { n: 2, text: "Relevant verification, documentation, and pull-request gates have passed.", checked: done },
        { n: 3, text: "Implementation Notes, Modified Files, and the final summary reflect the delivered state.", checked: done },
        { n: 4, text: "The completing-tasks skill was invoked before task closure.", checked: done },
      ],
      plan: `1. Read the code behind "${a.title.toLowerCase()}" and the tests around it.\n2. Write the failing test that names the outcome.\n3. Make the smallest change that passes it.\n4. Render the page at 100%, 125% and 150% and compare with the approved mockup.\n5. Update the service doc and open the pull request.`,
      notes: n % 2 ? "" : "Checked against the live config: the old default is still read by one caller, so the change keeps it for one release.",
      pr,
      ci: ciOf(id, pr),
      session: sessionOf(id),
      machines: machinesOf(id),
    };
    records.set(id, r);
    return r;
  }
  function describe(a, long, crit) {
    const n = num(a.id), t = a.title.toLowerCase();
    const parts = [
      `Today the answer to "${t}" takes an afternoon of reading three files and asking twice; after this change one command shows it. The current behaviour stays behind its existing flag, and the new path is measured before anything reads it.`,
      `Scope: the one module that owns the behaviour and its tests. Out of scope: the dashboards that read it, which follow in their own task once the numbers are in.`,
    ];
    if (long) parts.push(
      "## Background",
      "Two earlier attempts stalled on the same question: whether the window counts from the merge or from the first run after it. The second recorded its numbers before it stopped; they are still the best evidence and the plan below starts from them.",
      "Each run writes one row per step, so a rerun shows as a second row with the same commit. The aggregation has to keep both, because a rerun that passes after a failure is exactly what the review needs to see.",
      "## Duplicate Search",
      `${t}; ${t.split(" ").slice(-2).join(" ")} budget`,
      "## Duplicate Resolution",
      "Three candidates are Done prior work on the same module; one In Progress task draws the panel above it, which is distinct scope.",
    );
    if (crit.length) parts.push("## Start Criteria", "```yaml\nstart_criteria:\n" + crit.map((c) => `- id: ${c.id}\n  kind: ${c.kind}\n  ${c.kind === "sql" ? "query" : c.kind === "prom" ? "expr" : "path"}: ${c.expr}\n  ${c.cmp}: ${c.want}`).join("\n") + "\n```");
    if (n % 4 === 1 && !long) parts.push("## Duplicate Search", `${t}`);
    return parts.join("\n\n");
  }
  function sessionOf(id) {
    const m = machinesOf(id).find((x) => x.machine === "in-progress" && x.active);
    if (!m) return null;
    return { url: `claude.ai/code/session_demo${String(num(id)).padStart(4, "0")}`, model: m.model || "", state: m.state, at: m.active, steps: m.steps || 0 };
  }
  function ciOf(id, prs) {
    if (!prs.length) return null;
    const n = num(id), runs = [];
    const count = 3 + (n % 6), base = nowS() - count * 2400;
    let sha = 0x3f1a2c0 + n * 977;
    for (let i = 0; i < count; i++) {
      const rerun = i > 0 && (i + n) % 4 === 0;
      if (!rerun) sha += 0x1137;
      const last = i === count - 1;
      const head = prs[0];
      const result = last ? (head.merged ? "pass" : head.checks) : (i + n) % 3 === 0 ? "fail" : (i + n) % 7 === 0 ? "cancel" : "pass";
      runs.push({ sha: sha.toString(16).slice(-7), result, rerun, at: base + i * 2400, conflict: (n % 4 === 1 && i === 1) });
    }
    return { runs, reruns: runs.filter((r) => r.rerun).length, conflicts: runs.filter((r) => r.conflict).length, now: runs.at(-1).result };
  }

  // ---- tiny DOM helper ----
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style") el.style.cssText = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : String(kid));
    return el;
  }
  function toast(text) {
    const t = h("div", { class: "tm-toast" }, text);
    document.body.append(t);
    setTimeout(() => t.classList.add("out"), 1600);
    setTimeout(() => t.remove(), 2000);
  }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch {}
    // the page is served over plain http on a LAN address, where the async clipboard is refused: fall back to a selection
    const ta = h("textarea", { style: "position:fixed;opacity:0" }); ta.value = text; document.body.append(ta); ta.select();
    let ok = false; try { ok = document.execCommand("copy"); } catch {}
    ta.remove();
    return ok;
  }

  // ---- the task modal ----
  // Editing is per section: a section's ✎ opens its editor in place, with its own Save and Cancel, so the rest of the
  // task stays readable and live, and one section edits at a time. Checkboxes toggle without entering an editor.
  let openId = null, editing = null, draft = null, preview = false, layer = null;
  const NAMES = { title: "title", desc: "description", ac: "acceptance criteria", dod: "definition of done", plan: "plan", notes: "notes", details: "details" };
  const folded = (() => { try { return new Set(JSON.parse(localStorage.getItem("tm-folded") || "[]")); } catch { return new Set(); } })();
  function close() {
    layer?.remove(); layer = null; openId = null; editing = null; draft = null;
  }
  function open(id, opts = {}) {
    close();
    const r = record(id);
    if (!r) return;
    openId = id;
    layer = h("div", { id: "tmm", class: `scroll-${scroll}`, onclick: (e) => e.target === e.currentTarget && close() });
    if (opts.edit) return void (document.body.append(layer), edit(opts.edit));
    paint();
    document.body.append(layer);
    layer.querySelector(".tm-modal").focus();
  }
  function edit(key) {
    const r = record(openId);
    editing = key; preview = false;
    draft = key === "ac" || key === "dod" ? r[key].map((x) => ({ ...x })) : null;
    repaint();
    requestAnimationFrame(() => { const f = layer?.querySelector(".tm-ed .fv"); if (f) { f.focus(); f.setSelectionRange?.(f.value.length, f.value.length); } });
  }
  function cancel() { editing = null; draft = null; repaint(); }
  const STARTABLE = ["ready", "waiting", "needs_attention"];
  function startBtn(r) {
    return h("button", { class: "tm-btn start",
      title: r.state === "waiting" ? "Starts it now: its Start Criteria and dependencies gate only autopilot's claim" : `Opens a Remote Control session for ${r.id}`,
      onclick: (e) => {
        const b = e.currentTarget; b.disabled = true; b.textContent = "Starting…";
        // simulated: the session-start service answers, the task moves to In Progress and the session claims it
        setTimeout(() => {
          Object.assign(r, { state: "in_progress", entered: nowS(), session: { url: `claude.ai/code/session_demo${String(num(r.id)).padStart(4, "0")}`, model: "opus", state: "starting", at: nowS(), steps: 0 } });
          if (layer && openId === r.id) repaint();
          toast(`▶ Started a session for ${r.id} in tmux task-${num(r.id)}`);
        }, 900);
      } }, "▶ Start session");
  }
  function moveMenu(r) {
    const moves = ["ready", "waiting", "in_progress", "review", "needs_attention", "done"].filter((s) => s !== r.state);
    return h("div", { class: "tm-mv" },
      h("button", { class: "tm-btn", "aria-haspopup": "menu", onclick: (e) => { e.stopPropagation(); const m = e.currentTarget.nextSibling; m.hidden = !m.hidden; } }, "Move to ▾"),
      h("div", { class: "tm-menu", role: "menu", hidden: true }, moves.map((s) => h("button", { role: "menuitem",
        onclick: () => { r.state = s; r.entered = nowS(); repaint(); toast(`Moved ${r.id} to ${LANES[s]} (simulated)`); } }, "→ ", LANES[s]))));
  }
  function edBar() {
    return h("div", { class: "tm-edbar" }, h("span", { class: "k" }, "Ctrl+Enter saves · Esc cancels"),
      h("button", { class: "tm-btn", onclick: cancel }, "Cancel"), h("button", { class: "tm-btn save", onclick: save }, "Save"));
  }
  function paint() {
    const r = record(openId);
    const lane = LANES[r.state] || r.state;
    const modal = h("div", { class: "tm-modal", role: "dialog", "aria-label": `${r.id} ${r.title}`, tabindex: "-1" });
    const copyBtn = h("button", { class: "tm-copy", title: `Copy “${r.id} ${r.title}”`, "aria-label": `Copy ${r.id} and title`,
      onclick: async (e) => { const b = e.currentTarget; if (await copy(`${r.id} ${r.title}`)) { b.classList.add("ok"); b.lastChild.textContent = "Copied"; setTimeout(() => { b.classList.remove("ok"); b.lastChild.textContent = "Copy"; }, 1500); } } },
      h("span", { class: "g" }, "⧉"), h("span", null, "Copy"));
    const acts = [STARTABLE.includes(r.state) && !r.session && startBtn(r), moveMenu(r),
      h("button", { class: "tm-btn" }, "Hide task"), h("button", { class: "tm-btn warn" }, "Archive…")];
    modal.append(h("header", { class: "tm-head" },
      h("div", { class: "tm-meta" },
        h("span", { class: "tm-id" }, r.id), copyBtn,
        h("span", { class: "tm-lane", style: `--c:${LANE_COLOR[r.state] || "#94a3b8"}` }, h("i"), lane),
        h("a", { class: "tm-link", href: "#", onclick: (e) => { e.preventDefault(); toast("Opens the Star Map at this task's dot"); } }, "Open in Star Map ↗"),
        h("span", { class: "tm-acts" }, acts),
        h("button", { class: "tm-x", "aria-label": "Close", onclick: close }, "✕")),
      editing === "title"
        ? h("div", { class: "tm-ed title" }, h("textarea", { class: "tm-title fv", rows: 1, "aria-label": "Title" }, r.title), edBar())
        : h("h2", { class: "tm-title" }, r.title, h("button", { class: "tm-pen", title: "Edit the title", "aria-label": "Edit the title", onclick: () => edit("title") }, "✎"))));
    modal.append(h("div", { class: "tm-body" }, left(r), rail(r)));
    layer.replaceChildren(modal);
    layer.className = `scroll-${scroll}`;
    // measured once the layer is in the document: a detached textarea has no scroll height
    if (editing) requestAnimationFrame(() => layer?.querySelectorAll(".tm-ed textarea.fv").forEach(grow));
  }
  function readList() { if (draft) layer.querySelectorAll(".tm-ed textarea.fv").forEach((t, i) => draft[i] && (draft[i].text = t.value)); }
  function save() {
    // simulated save: the fields keep what was typed, as the page would after its PUT answers
    const r = record(openId), ed = layer.querySelector(".tm-ed"), key = editing;
    if (!ed) return;
    let changed = false;
    if (key === "title") { const v = ed.querySelector("textarea").value.trim(); changed = !!v && v !== r.title; if (v) r.title = v; }
    else if (key === "desc" || key === "plan" || key === "notes") {
      const f = { desc: "description", plan: "plan", notes: "notes" }[key], v = preview ? draft : ed.querySelector("textarea").value;
      changed = v !== r[f]; r[f] = v;
    } else if (key === "ac" || key === "dod") {
      readList();
      const next = draft.filter((x) => x.text.trim()).map((x, i) => ({ ...x, n: i + 1 }));
      changed = JSON.stringify(next) !== JSON.stringify(r[key]); r[key] = next;
    } else if (key === "details") ed.querySelectorAll("select[data-f]").forEach((s) => { if ((r[s.dataset.f] || "") !== s.value) { r[s.dataset.f] = s.value; changed = true; } });
    editing = null; draft = null; repaint();
    toast(changed ? `✓ Saved ${NAMES[key]}` : "Nothing changed");
  }
  function repaint() { const y = [...layer.querySelectorAll(".tm-col")].map((c) => c.scrollTop); paint(); layer.querySelectorAll(".tm-col").forEach((c, i) => (c.scrollTop = y[i] || 0)); }
  function grow(t) { const fit = () => { t.style.height = "auto"; t.style.height = t.scrollHeight + 2 + "px"; }; if (!t.classList.contains("long")) { fit(); t.oninput = fit; } }

  function section(key, title, count, body, opts = {}) {
    const fold = scroll === "fold" && opts.rail;
    const shut = fold && folded.has(key) && editing !== key;
    const pen = opts.edit && editing !== key && h("button", { class: "tm-pen", title: `Edit ${NAMES[key]}`, "aria-label": `Edit ${NAMES[key]}`, onclick: (e) => { e.stopPropagation(); edit(key); } }, "✎ Edit");
    const head = h(fold ? "button" : "div", { class: "tm-sh", "aria-expanded": fold ? String(!shut) : null,
      onclick: fold ? () => { shut ? folded.delete(key) : folded.add(key); try { localStorage.setItem("tm-folded", JSON.stringify([...folded])); } catch {} repaint(); } : null },
      fold && h("span", { class: "chev" }, shut ? "▸" : "▾"), h("span", { class: "t" }, title), count != null && h("span", { class: "n" }, count), opts.aside);
    return h("section", { class: `tm-sec ${key}${shut ? " shut" : ""}${editing === key ? " on" : ""}` }, h("div", { class: "tm-shw" }, head, pen), !shut && body);
  }

  function markdown(text) {
    const out = [];
    for (const raw of text.split(/\n\n/)) {
      if (raw.startsWith("```")) {
        if (/start_criteria:/.test(raw)) { out.push(h("div", { class: "tm-moved" }, "Start Criteria are drawn in the side panel, each with its result →")); continue; }
        out.push(h("pre", null, raw.replace(/^```\w*\n?|```$/g, "")));
      } else if (raw.startsWith("## ")) out.push(h("h4", null, raw.slice(3)));
      else out.push(h("p", null, raw));
    }
    return out;
  }
  function checks(r, key) {
    const items = r[key], word = key === "ac" ? "criterion" : "item";
    if (editing === key) {
      const rm = (i) => { readList(); draft.splice(i, 1); repaint(); };
      const add = () => { readList(); draft.push({ n: draft.length + 1, text: "", checked: false }); repaint(); [...layer.querySelectorAll(".tm-ed textarea.fv")].pop()?.focus(); };
      return h("div", { class: "tm-ed list" },
        draft.map((it, i) => h("div", { class: "tm-erow" }, h("span", { class: "nn" }, `#${i + 1}`),
          h("textarea", { class: "fv", rows: 1, "aria-label": `${NAMES[key]} #${i + 1}`, placeholder: `Describe the ${word}` }, it.text),
          h("button", { class: "tm-rm", title: `Remove #${i + 1}`, "aria-label": `Remove #${i + 1}`, onclick: () => rm(i) }, "✕"))),
        h("button", { class: "tm-add", onclick: add }, `+ Add ${word}`), edBar());
    }
    return h("div", { class: "tm-list" }, items.map((it) => h("label", { class: `tm-item${it.checked ? " done" : ""}` },
      h("input", { type: "checkbox", checked: it.checked, onchange: (e) => { it.checked = e.target.checked; repaint(); toast(`${it.checked ? "Checked" : "Unchecked"} ${key === "ac" ? "criterion" : "item"} #${it.n} (simulated)`); } }),
      h("span", { class: "nn" }, `#${it.n}`), h("span", { class: "tx" }, it.text))));
  }
  function textEditor(key, value, long) {
    if (editing !== key) return null;
    if (key !== "desc") return h("div", { class: "tm-ed" }, h("textarea", { class: `fv${long ? " long" : ""}`, "aria-label": NAMES[key] }, value), edBar());
    const tab = (on) => () => { if (!preview) draft = layer.querySelector(".tm-ed textarea").value; preview = on; repaint(); };
    const text = draft ?? value;
    return h("div", { class: "tm-ed" },
      h("div", { class: "tm-tabs", role: "tablist" }, h("button", { role: "tab", class: preview ? "" : "on", onclick: tab(false) }, "Write"), h("button", { role: "tab", class: preview ? "on" : "", onclick: tab(true) }, "Preview"),
        h("span", { class: "k" }, "Markdown")),
      preview ? h("div", { class: "tm-md prev" }, markdown(text)) : h("textarea", { class: "fv long", "aria-label": "Description" }, text), edBar());
  }
  function left(r) {
    const count = (xs) => `${xs.filter((x) => x.checked).length}/${xs.length}`;
    return h("div", { class: "tm-col tm-left" },
      section("desc", "Description", null, textEditor("desc", r.description, true) || h("div", { class: "tm-md" }, markdown(r.description)), { edit: true }),
      section("ac", "Acceptance criteria", count(r.ac), checks(r, "ac"), { edit: true }),
      section("dod", "Definition of done", count(r.dod), checks(r, "dod"), { edit: true }),
      section("plan", "Implementation plan", null, textEditor("plan", r.plan, true) || h("div", { class: "tm-md pre" }, r.plan), { edit: true }),
      section("notes", "Notes", null, textEditor("notes", r.notes, true) || (r.notes ? h("div", { class: "tm-md pre" }, r.notes) : h("div", { class: "none" }, "—")), { edit: true }));
  }

  function lanePill(state) { return h("span", { class: "tm-lane sm", style: `--c:${LANE_COLOR[state] || "#94a3b8"}` }, h("i"), LANES[state] || state); }
  function rail(r) {
    const now = nowS();
    const kids = [];
    // 1. status: its lane and for how long; the moves and Start session are in the header's actions
    kids.push(section("status", "Status", null, h("div", { class: "tm-status" },
      h("div", { class: "row" }, lanePill(r.state), h("span", { class: "k" }, `for ${ago(now - r.entered)}`))), { rail: true }));
    // 2. the session that holds it
    kids.push(section("session", "Session", null, r.session
      ? h("div", { class: "tm-session" },
        h("a", { href: "#", class: "big", title: r.session.url, onclick: (e) => { e.preventDefault(); toast(`Opens ${r.session.url} in a new tab`); } }, h("span", { class: "p" }), "Open the claiming session ↗"),
        h("div", { class: "k" }, `${r.session.model} · ${r.session.state.replace(/_/g, " ")} · ${ago(now - r.session.at)} ago · ${r.session.steps} steps`))
      : h("div", { class: "none" }, r.state === "in_progress" ? "No session has claimed it: worked by hand" : STARTABLE.includes(r.state) ? "No session holds this task. ▶ Start session, top right, opens one." : "No session holds this task"), { rail: true }));
    // 3. Start Criteria, parsed from the description's start_criteria block
    if (r.criteria.length) {
      const met = r.criteria.filter((c) => c.met).length;
      kids.push(section("criteria", "Start Criteria", `${met}/${r.criteria.length} met`, h("div", { class: "tm-crit" }, r.criteria.map((c) => h("div", { class: `c ${c.met ? "met" : "unmet"}` },
        h("div", { class: "top" }, h("span", { class: "st" }, c.met ? "✓ met" : "○ unmet"), h("span", { class: "kind" }, c.kind), h("code", { class: "cid" }, c.id)),
        h("code", { class: "expr", title: c.expr }, c.expr),
        h("div", { class: "k" }, c.time
          ? `opens ${stamp(c.want)} · ${c.note}`
          : `${c.cmp.replace("_", " ")} ${c.want}${c.unit ? " " + c.unit : ""} · last ${c.got}`, ` · checked ${clock(c.checked)}`)))), { rail: true }));
    }
    // 4. pull requests
    kids.push(section("prs", "Pull requests", r.pr.length || null, r.pr.length ? h("div", { class: "tm-prs" }, r.pr.map((p) => h("div", { class: "pr" },
      h("a", { href: p.url, target: "_blank", rel: "noopener" }, `#${p.number} ↗`),
      h("span", { class: `chk ${p.merged ? "merged" : p.checks}` }, h("i"), p.merged ? "merged" : `checks ${p.checks}`),
      p.threads ? h("span", { class: "thr" }, `${p.threads} open thread${p.threads === 1 ? "" : "s"}`) : h("span", { class: "k" }, "no open threads"),
      p.stale && h("span", { class: "thr" }, "behind main")))) : h("div", { class: "none" }, "None yet"), { rail: true }));
    // 5. CI history (shape per the CI-on-the-Star-Map design)
    if (r.ci) {
      const c = r.ci;
      kids.push(section("ci", "CI history", null, h("div", { class: "tm-ci" },
        h("div", { class: "nums" },
          h("span", null, h("b", null, c.runs.length), " runs"), h("span", null, h("b", null, c.reruns), " reruns"),
          h("span", { class: c.conflicts ? "warn" : "" }, h("b", null, c.conflicts), " conflicts"),
          h("span", { class: `chk ${c.now}` }, h("i"), `now ${c.now}`)),
        h("div", { class: "strip" }, c.runs.map((x) => h("i", { class: `${x.result}${x.rerun ? " rerun" : ""}${x.conflict ? " conflict" : ""}`,
          title: `${x.sha} · ${x.result}${x.rerun ? " · rerun" : ""}${x.conflict ? " · hit a merge conflict" : ""} · ${clock(x.at)}` }))),
        h("div", { class: "k draft" }, "Oldest to newest, one mark per run; a ring is a rerun of the same commit. Final shape follows the CI on the Star Map design.")), { rail: true }));
    }
    // 6. dependencies, both ways
    const holds = board().filter((a) => a.dependencies?.includes(r.id));
    const depRow = (id) => { const a = byId(id); return h("button", { class: "dep", onclick: () => open(id) }, h("span", { class: "id" }, id), h("span", { class: "tt" }, a?.title || "not on the board"), a && lanePill(a.state)); };
    kids.push(section("deps", "Dependencies", (r.dependencies.length + holds.length) || null, h("div", { class: "tm-deps" },
      h("div", { class: "lb" }, "Depends on"), r.dependencies.length ? r.dependencies.map(depRow) : h("div", { class: "none" }, "—"),
      holds.length ? [h("div", { class: "lb" }, "Holds"), holds.slice(0, 6).map((a) => depRow(a.id)), holds.length > 6 && h("div", { class: "k" }, `+${holds.length - 6} more`)] : null), { rail: true }));
    // 7. machines the task is in
    kids.push(section("machines", "Machines", r.machines.length || null, r.machines.length ? h("div", { class: "tm-mach" }, r.machines.map((m) => h("details", { class: "m" },
      h("summary", null, h("span", { class: "p" }), h("b", null, m.machine), h("span", { class: "s" }, m.state.replace(/_/g, " ")), h("span", { class: "k" }, m.active ? `${ago(now - m.active)} ago` : "")),
      h("ol", null, (m.trail || []).slice(-5).map((t) => h("li", null, h("code", null, t.event), " → ", t.state.replace(/_/g, " "), h("span", { class: "k" }, ` ${clock(t.at)}`))))))) : h("div", { class: "none" }, "In no machine right now"), { rail: true }));
    // 8. the task file's fields
    const ed = editing === "details";
    const sel = (f, opts) => ed ? h("select", { class: "fv", "data-f": f, "aria-label": f }, opts.map((o) => h("option", { value: o, selected: o === (r[f] || "") }, o || "—"))) : h("span", null, r[f] || "—");
    kids.push(section("details", "Details", null, h("div", { class: ed ? "tm-ed" : "" }, h("table", { class: "tm-props" }, h("tbody", null,
      h("tr", null, h("td", null, "profile"), h("td", null, sel("profile", ["", "@agent-light-low", "@agent-standard-medium", "@agent-standard-high", "@agent-deep-medium", "@agent-deep-high"]))),
      h("tr", null, h("td", null, "priority"), h("td", null, sel("priority", ["", ...PRIORITIES]))),
      h("tr", null, h("td", null, "labels"), h("td", null, h("span", { class: "chips" }, r.labels.map((l) => h("span", { class: `chip${l === "needs-human" ? " nh" : ""}` }, l))))),
      h("tr", null, h("td", null, "milestone"), h("td", null, sel("milestone", ["", r.milestone, "m-2", "m-3"].filter((v, i, a) => a.indexOf(v) === i)))),
      h("tr", null, h("td", null, "created"), h("td", null, h("span", { class: "k" }, `${ago(now - r.created)} ago`))))), ed && edBar()), { rail: true, edit: true }));
    return h("div", { class: "tm-col tm-rail" }, kids);
  }

  // ---- Connect a tracker ----
  // Setup is a CLI: `starpulse connect <tracker>` checks the tracker answers, then writes starpulse.toml's [board]
  // table, so the modal shows commands to copy rather than a table to hand-edit.
  const TRACKERS = [
    { key: "native", name: "StarPulse board", badge: "connected", about: "StarPulse's own Markdown board, drawn until you connect another. Moves made on the page are written to it.",
      steps: [
        { text: "Nothing to set up: the board is created empty in .starpulse/board on the first serve." },
        { text: "To keep it somewhere else, or give it a machine file that decides which moves are offered:", cmd: "starpulse connect native --path .starpulse/board --machine board.yaml" },
      ] },
    { key: "backlog", name: "Backlog.md", about: "Draws a Backlog.md project's tasks and writes each move with its backlog CLI.",
      steps: [
        { text: "Install the Backlog.md CLI, which writes each move:", cmd: "npm i -g backlog.md" },
        { text: "Connect the project's backlog/ directory:", cmd: "starpulse connect backlog --path backlog", out: "✓ Read 36 tasks in 5 lanes from backlog/ · wrote [board] to starpulse.toml" },
        { text: "Restart the server to draw it:", cmd: "starpulse serve" },
      ] },
    { key: "jira", name: "Jira", badge: "read-only", about: "Imports a Jira project's workflow as the Board machine and polls its issues. Moves are made in Jira.",
      steps: [
        { text: "Create an API token in your Atlassian account settings, then export it:", cmd: "export JIRA_TOKEN=<your API token>" },
        { text: "Connect the project. It checks the site and the token, imports the workflow and reads the issues once:",
          cmd: 'starpulse connect jira --url https://<your-site>.atlassian.net --project PAY --workflow "Payments Software Workflow" --user <your Atlassian email>',
          out: "✓ Imported Payments Software Workflow (7 states) · read 42 issues from PAY · wrote [board] to starpulse.toml" },
        { text: "Restart the server to draw it:", cmd: "starpulse serve" },
      ] },
  ];
  function cmdBlock(cmd) {
    return h("div", { class: "cmd" }, h("span", { class: "pr" }, "$"), h("code", null, cmd),
      h("button", { class: "tm-copy", "aria-label": `Copy ${cmd}`, onclick: async (e) => { const b = e.currentTarget; if (await copy(cmd)) { b.classList.add("ok"); b.lastChild.textContent = "Copied"; setTimeout(() => { b.classList.remove("ok"); b.lastChild.textContent = "Copy"; }, 1500); } } },
        h("span", { class: "g" }, "⧉"), h("span", null, "Copy")));
  }
  function tracker(opts = {}) {
    close();
    const openSet = new Set(opts.expand || []);
    layer = h("div", { id: "tmm", class: "tracker", onclick: (e) => e.target === e.currentTarget && close() });
    const paintT = () => {
      const found = opts.hint || fx().hint;
      layer.replaceChildren(h("div", { class: "tm-modal tk", role: "dialog", "aria-label": "Connect a tracker", tabindex: "-1" },
        h("header", { class: "tk-head" }, h("h2", null, "Connect a tracker"), h("button", { class: "tm-x", "aria-label": "Close", onclick: close }, "✕")),
        h("p", { class: "k" }, "StarPulse draws its own Markdown board until you connect another. ", h("code", null, "starpulse connect"),
          " checks that the tracker answers, then writes the board settings into ", h("code", null, "starpulse.toml"), " for you; ", h("code", null, "starpulse connect --help"), " lists every option."),
        found && h("div", { class: "found", role: "status" }, "Found a Backlog.md project in ./backlog; StarPulse is drawing its own board. To draw that project instead:", cmdBlock("starpulse connect backlog --path backlog")),
        h("div", { class: "tk-list" }, TRACKERS.map((t) => {
          const on = openSet.has(t.key);
          return h("section", { class: `tk${on ? " on" : ""}` },
            h("button", { class: "tk-row", "aria-expanded": String(on), onclick: () => { on ? openSet.delete(t.key) : openSet.add(t.key); paintT(); } },
              h("span", { class: "chev" }, on ? "▾" : "▸"), h("b", null, t.name), t.badge && h("span", { class: `badge ${t.badge}` }, t.badge), h("span", { class: "about" }, t.about)),
            on && h("ol", { class: "tk-body" }, t.steps.map((st) => h("li", null, h("div", null, st.text), st.cmd && cmdBlock(st.cmd), st.out && h("div", { class: "out" }, h("span", { class: "k" }, "prints "), st.out)))));
        }))));
    };
    paintT();
    document.body.append(layer);
  }

  // ---- review bar: scroll variant and text size ----
  function applySize() {
    // the page's own text-size setting writes --fs inline after it mounts, so the review size wins by !important
    let el = document.getElementById("tm-fs");
    if (!el) { el = h("style", { id: "tm-fs" }); document.head.append(el); }
    el.textContent = size === "100" ? "" : `html { --fs: ${+size / 100} !important; font-size: ${size}% !important; }`;
  }
  function bar() {
    if (bare) return;
    const seg = (label, vals, cur, set, names) => h("span", { class: "seg" }, h("span", { class: "lb" }, label), vals.map((v) => h("button", { class: v === cur ? "on" : "", onclick: () => set(v) }, names ? names[v] : `${v}%`)));
    const b = h("div", { id: "tm-bar" }, h("b", null, "Mockup"),
      seg("Scroll", SCROLLS, scroll, (v) => { scroll = v; sync(); if (openId) repaint(); }, { split: "Columns apart", shared: "Shared", fold: "Folding rail" }),
      seg("Text", SIZES, size, (v) => { size = v; applySize(); sync(); }));
    document.getElementById("tm-bar")?.remove();
    document.body.append(b);
  }
  function sync() {
    const p = new URLSearchParams(location.search);
    scroll === "split" ? p.delete("scroll") : p.set("scroll", scroll);
    size === "100" ? p.delete("fs") : p.set("fs", size);
    try { history.replaceState(null, "", location.pathname + "?" + p.toString()); } catch {}
    bar();
  }

  // ---- taking over the page's own openers ----
  let press = null;
  function boot() {
    document.head.append(h("style", null, CSS));
    applySize();
    addEventListener("pointerdown", (e) => { press = { x: e.clientX, y: e.clientY }; }, true);
    addEventListener("click", (e) => {
      const t = e.target;
      if (layer && t.closest("#tmm")) { if (!t.closest(".tm-mv")) layer.querySelectorAll(".tm-menu").forEach((m) => (m.hidden = true)); return; }
      const moved = press && Math.hypot(e.clientX - press.x, e.clientY - press.y) > 5;
      const tb = t.closest("#kb .trackerw > .tbtn");
      if (tb) { e.stopPropagation(); e.preventDefault(); tracker(); return; }
      const hb = t.closest("#kb .heldby .hb");
      if (hb) { e.stopPropagation(); open(hb.textContent.replace(/⛓.*/, "").trim()); return; }
      const card = t.closest("#kb .card");
      if (card && !moved && !t.closest(".play, a, button")) { e.stopPropagation(); open(card.dataset.id); }
    }, true);
    addEventListener("keydown", (e) => {
      if (layer && e.key === "Escape") { e.stopImmediatePropagation(); e.preventDefault(); const m = layer.querySelector(".tm-menu:not([hidden])"); if (m) m.hidden = true; else if (editing) cancel(); else close(); return; }
      if (layer && editing && e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.stopImmediatePropagation(); save(); return; }
      const card = e.target.closest?.("#kb .card");
      if (!layer && card && (e.key === "Enter" || e.key === " ") && e.target === card) { e.stopImmediatePropagation(); e.preventDefault(); open(card.dataset.id); }
    }, true);
    bar();
    if (preset) {
      const go = () => {
        if (!document.querySelector("#kb .card")) return void setTimeout(go, 120);
        if (preset.tracker) tracker(preset);
        else if (preset.open) open(preset.open(), preset);
      };
      go();
    }
  }

  const CSS = `
#tmm { position: fixed; inset: 0; z-index: 60; display: grid; place-items: center; background: rgba(2,4,10,.62); backdrop-filter: blur(2px); animation: kb-scrim .15s ease-out; font-family: Inter, system-ui, sans-serif; }
#tmm .tm-modal { box-sizing: border-box; width: clamp(860px, 65vw, 1500px); max-width: calc(100vw - 32px); height: min(84vh, 980px); display: flex; flex-direction: column; border-radius: 12px; outline: none;
  background: rgba(12,19,34,.985); border: 1px solid rgba(148,163,184,.22); box-shadow: 0 30px 80px rgba(0,0,0,.6); color: var(--ink); font-size: calc(12.5px * var(--fs)); line-height: 1.6; animation: kb-modal .15s ease-out; overflow: hidden; }
#tmm .k { color: var(--muted); font-size: calc(11px * var(--fs)); }
#tmm .none { color: #475569; }
#tmm a { color: #a78bfa; text-decoration: none; } #tmm a:hover { text-decoration: underline; }
#tmm code, #tmm pre, #tmm kbd { font-family: "JetBrains Mono", ui-monospace, monospace; }
#tmm kbd { font-size: calc(9.5px * var(--fs)); padding: 0 4px; border-radius: 3px; border: 1px solid rgba(148,163,184,.25); color: var(--muted); margin-left: 4px; }
/* header: one meta row, then the title across the whole width */
#tmm .tm-head { flex: none; padding: 14px 20px 14px 26px; border-bottom: 1px solid rgba(148,163,184,.12); display: flex; flex-direction: column; gap: 6px; }
#tmm .tm-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 10px; min-height: 30px; }
#tmm .tm-id { font: calc(12px * var(--fs)) "JetBrains Mono", monospace; color: #b8c4d8; letter-spacing: .02em; }
#tmm .tm-copy { cursor: pointer; display: inline-flex; align-items: center; gap: 5px; padding: 2px 9px; border-radius: 6px; border: 1px solid rgba(148,163,184,.22); background: none; color: #94a3b8; font: inherit; font-size: calc(11px * var(--fs)); }
#tmm .tm-copy:hover { color: var(--ink); border-color: rgba(148,163,184,.5); } #tmm .tm-copy.ok { color: #34d399; border-color: rgba(52,211,153,.5); }
#tmm .tm-copy .g { font-size: calc(12px * var(--fs)); }
#tmm .tm-lane { display: inline-flex; align-items: center; gap: 6px; padding: 1px 9px; border-radius: 999px; background: color-mix(in srgb, var(--c) 14%, transparent); color: var(--c); font-size: calc(11px * var(--fs)); white-space: nowrap; }
#tmm .tm-lane i { width: 6px; height: 6px; border-radius: 50%; background: var(--c); box-shadow: 0 0 6px var(--c); }
#tmm .tm-lane.sm { font-size: calc(10px * var(--fs)); padding: 0 7px; }
#tmm .tm-link { font-size: calc(11px * var(--fs)); white-space: nowrap; }
#tmm .tm-acts { margin-left: auto; display: flex; gap: 8px; align-items: center; }
#tmm .tm-btn { cursor: pointer; padding: 4px 10px; border-radius: 6px; border: 1px solid rgba(148,163,184,.25); background: none; color: #94a3b8; font: inherit; font-size: calc(11.5px * var(--fs)); white-space: nowrap; }
#tmm .tm-btn:hover:not(:disabled) { color: var(--ink); border-color: rgba(148,163,184,.5); } #tmm .tm-btn:disabled { opacity: .45; cursor: default; }
#tmm .tm-btn.warn { color: #fb7185; border-color: rgba(251,113,133,.45); } #tmm .tm-btn.edit, #tmm .tm-btn.save { color: #c4b5fd; border-color: rgba(167,139,250,.55); background: rgba(167,139,250,.10); }
#tmm .tm-btn.start { color: #34d399; border-color: rgba(52,211,153,.45); background: rgba(52,211,153,.08); }
#tmm .tm-x { all: unset; cursor: pointer; color: var(--muted); font-size: calc(14px * var(--fs)); padding: 2px 6px; margin-left: 4px; } #tmm .tm-x:hover { color: var(--ink); }
#tmm .tm-title { margin: 0; font-size: calc(18px * var(--fs)); font-weight: 500; line-height: 1.35; color: var(--ink); overflow-wrap: anywhere; }
#tmm textarea.tm-title { width: 100%; box-sizing: border-box; resize: none; }
/* body: two columns */
#tmm .tm-body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) clamp(320px, 31%, 440px); }
#tmm .tm-col { min-width: 0; padding: 18px 26px 26px; display: flex; flex-direction: column; gap: 22px; scrollbar-width: thin; scrollbar-color: rgba(148,163,184,.25) transparent; }
#tmm .tm-rail { padding: 16px 20px 24px; gap: 16px; background: rgba(148,163,184,.03); border-left: 1px solid rgba(148,163,184,.10); }
#tmm.scroll-split .tm-col, #tmm.scroll-fold .tm-col { overflow-y: auto; }
#tmm.scroll-shared .tm-body { overflow-y: auto; align-items: start; } #tmm.scroll-shared .tm-rail { min-height: 100%; box-sizing: border-box; }
#tmm .tm-sec { display: flex; flex-direction: column; gap: 7px; }
#tmm .tm-sh { all: unset; display: flex; align-items: center; gap: 8px; font-size: calc(10px * var(--fs)); letter-spacing: .14em; text-transform: uppercase; color: var(--muted); }
#tmm button.tm-sh { cursor: pointer; } #tmm button.tm-sh:hover { color: var(--ink); } #tmm .tm-sh .n { letter-spacing: 0; text-transform: none; color: #94a3b8; }
#tmm .tm-sh .chev { width: 10px; letter-spacing: 0; }
#tmm .tm-rail .tm-sec + .tm-sec { border-top: 1px solid rgba(148,163,184,.08); padding-top: 14px; }
/* left column content */
#tmm .tm-md { color: #b8c4d8; max-width: 92ch; } #tmm .tm-md p { margin: 0 0 10px; } #tmm .tm-md.pre { white-space: pre-wrap; }
#tmm .tm-md h4 { margin: 16px 0 6px; font-size: calc(11px * var(--fs)); font-weight: 500; color: #94a3b8; letter-spacing: .06em; text-transform: uppercase; }
#tmm .tm-md pre { margin: 0 0 10px; padding: 8px 10px; border-radius: 6px; background: rgba(2,6,23,.7); white-space: pre-wrap; font-size: calc(11px * var(--fs)); }
#tmm .tm-moved { margin: 0 0 10px; padding: 6px 10px; border-radius: 6px; border: 1px dashed rgba(148,163,184,.25); color: var(--muted); font-size: calc(11px * var(--fs)); }
#tmm .tm-list { display: flex; flex-direction: column; gap: 4px; }
#tmm .tm-item { display: grid; grid-template-columns: 16px 26px minmax(0, 1fr); gap: 6px; align-items: start; color: #b8c4d8; }
#tmm .tm-item input[type=checkbox] { margin: 4px 0 0; accent-color: #a78bfa; } #tmm .tm-item .nn { color: #64748b; font-size: calc(11px * var(--fs)); padding-top: 1px; }
#tmm .tm-item.done .tx { color: #7c8aa3; }
#tmm .tm-add { all: unset; cursor: pointer; color: #a78bfa; font-size: calc(11px * var(--fs)); padding: 2px 0 0 32px; } #tmm .tm-add:hover { color: #c4b5fd; }
/* per-section editing: ✎ beside each heading, the editor in place with its own bar */
#tmm .tm-shw { display: flex; align-items: center; gap: 8px; min-height: 22px; }
#tmm .tm-pen { all: unset; cursor: pointer; margin-left: auto; padding: 1px 8px; border-radius: 5px; color: #64748b; font-size: calc(11px * var(--fs)); opacity: .55; }
#tmm .tm-sec:hover .tm-pen, #tmm .tm-pen:focus-visible { opacity: 1; } #tmm .tm-pen:hover { color: #c4b5fd; background: rgba(167,139,250,.12); } #tmm .tm-pen:focus-visible { outline: 1px solid rgba(167,139,250,.6); }
#tmm h2.tm-title .tm-pen { margin-left: 8px; vertical-align: 2px; font-size: calc(12px * var(--fs)); opacity: 0; } #tmm .tm-head:hover h2.tm-title .tm-pen, #tmm h2.tm-title .tm-pen:focus-visible { opacity: 1; }
#tmm .tm-sec.on { margin: -8px -12px; padding: 8px 12px 10px; border-radius: 8px; background: rgba(167,139,250,.05); box-shadow: inset 0 0 0 1px rgba(167,139,250,.35); }
#tmm .tm-ed { display: flex; flex-direction: column; gap: 8px; } #tmm .tm-ed.title { gap: 6px; }
#tmm .tm-edbar { display: flex; justify-content: flex-end; align-items: center; gap: 8px; } #tmm .tm-edbar .k { margin-right: auto; }
#tmm .tm-tabs { display: flex; gap: 2px; align-items: center; } #tmm .tm-tabs button { all: unset; cursor: pointer; padding: 2px 10px; border-radius: 5px; color: #94a3b8; font-size: calc(11px * var(--fs)); }
#tmm .tm-tabs button.on { background: rgba(167,139,250,.18); color: var(--ink); } #tmm .tm-tabs .k { margin-left: auto; }
#tmm .tm-md.prev { min-height: 140px; padding: 8px 10px; border-radius: 6px; border: 1px dashed rgba(148,163,184,.22); }
#tmm .tm-ed textarea.fv.long { min-height: 220px; max-height: 52vh; padding: 8px 10px; font-family: "JetBrains Mono", ui-monospace, monospace; font-size: calc(11.5px * var(--fs)); }
#tmm .tm-erow { display: grid; grid-template-columns: 26px minmax(0, 1fr) 24px; gap: 6px; align-items: start; } #tmm .tm-erow .nn { color: #64748b; font-size: calc(11px * var(--fs)); padding-top: 4px; }
#tmm .tm-rm { all: unset; cursor: pointer; text-align: center; color: #64748b; padding-top: 3px; } #tmm .tm-rm:hover { color: #fb7185; }
#tmm .tm-acts .tm-menu { left: auto; right: 0; }
#tmm .fv { box-sizing: border-box; width: 100%; font: inherit; line-height: 1.5; color: var(--ink); background: rgba(148,163,184,.06); border: 1px solid rgba(148,163,184,.22); border-radius: 6px; padding: 3px 8px; }
#tmm textarea.fv { resize: none; overflow: hidden; }
#tmm .fv:focus { outline: none; border-color: rgba(167,139,250,.65); } #tmm textarea.fv.long { min-height: 140px; resize: vertical; overflow: auto; } #tmm select.fv { width: auto; min-width: 180px; } #tmm select option { background: #0c1322; }
/* rail content */
#tmm .tm-status .row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; } #tmm .tm-status .acts { margin-top: 8px; }
#tmm .tm-status .tm-lane { font-size: calc(12px * var(--fs)); padding: 2px 10px; }
#tmm .tm-mv { position: relative; }
#tmm .tm-menu { position: absolute; z-index: 5; top: calc(100% + 4px); left: 0; min-width: 180px; padding: 4px; border-radius: 8px; border: 1px solid rgba(148,163,184,.3); background: #0b1220; box-shadow: 0 10px 30px rgba(0,0,0,.5); display: flex; flex-direction: column; }
#tmm .tm-menu[hidden] { display: none; } #tmm .tm-menu button { all: unset; cursor: pointer; padding: 4px 10px; border-radius: 5px; color: #b8c4d8; font-size: calc(11.5px * var(--fs)); } #tmm .tm-menu button:hover { background: rgba(167,139,250,.14); color: var(--ink); }
#tmm .tm-session .big { display: inline-flex; align-items: center; gap: 8px; font-size: calc(12.5px * var(--fs)); }
#tmm .tm-session .p, #tmm .tm-mach .p { width: 7px; height: 7px; border-radius: 50%; background: #fbbf24; box-shadow: 0 0 8px #fbbf24; display: inline-block; flex: none; }
#tmm .tm-crit { display: flex; flex-direction: column; gap: 8px; }
#tmm .tm-crit .c { padding: 7px 9px; border-radius: 7px; border: 1px solid rgba(148,163,184,.14); display: flex; flex-direction: column; gap: 3px; min-width: 0; }
#tmm .tm-crit .c.met { border-color: rgba(52,211,153,.35); background: rgba(52,211,153,.05); } #tmm .tm-crit .c.unmet { border-color: rgba(251,191,36,.30); background: rgba(251,191,36,.04); }
#tmm .tm-crit .top { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; min-width: 0; }
#tmm .tm-crit .st { font-size: calc(11px * var(--fs)); font-weight: 500; } #tmm .tm-crit .met .st { color: #34d399; } #tmm .tm-crit .unmet .st { color: #fbbf24; }
#tmm .tm-crit .kind { font: calc(10px * var(--fs)) "JetBrains Mono", monospace; padding: 0 6px; border-radius: 4px; background: rgba(148,163,184,.12); color: #b8c4d8; }
#tmm .tm-crit .cid { font-size: calc(10.5px * var(--fs)); color: #94a3b8; overflow-wrap: anywhere; }
#tmm .tm-crit .expr { font-size: calc(10.5px * var(--fs)); color: #dbe4f3; overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
#tmm .tm-prs .pr { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; padding: 2px 0; }
#tmm .chk { display: inline-flex; align-items: center; gap: 5px; font-size: calc(11px * var(--fs)); color: #b8c4d8; } #tmm .chk i { width: 7px; height: 7px; border-radius: 50%; background: #94a3b8; }
#tmm .chk.pass i { background: #34d399; } #tmm .chk.fail i { background: #fb7185; } #tmm .chk.pending i { background: #fbbf24; } #tmm .chk.merged i { background: #a78bfa; } #tmm .chk.cancel i { background: #64748b; }
#tmm .thr { font-size: calc(11px * var(--fs)); color: #fbbf24; }
#tmm .tm-ci .nums { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: calc(11.5px * var(--fs)); color: #94a3b8; } #tmm .tm-ci .nums b { color: var(--ink); font-weight: 500; } #tmm .tm-ci .nums .warn b { color: #fbbf24; }
#tmm .tm-ci .strip { display: flex; flex-wrap: wrap; gap: 4px; margin: 8px 0 4px; }
#tmm .tm-ci .strip i { width: calc(12px * var(--fs)); height: calc(12px * var(--fs)); border-radius: 3px; background: #64748b; box-sizing: border-box; }
#tmm .tm-ci .strip i.pass { background: #34d399; } #tmm .tm-ci .strip i.fail { background: #fb7185; } #tmm .tm-ci .strip i.pending { background: #fbbf24; }
#tmm .tm-ci .strip i.rerun { border-radius: 50%; } #tmm .tm-ci .strip i.conflict { outline: 2px solid #fbbf24; outline-offset: 1px; }
#tmm .tm-ci .draft { font-size: calc(10px * var(--fs)); }
#tmm .tm-deps { display: flex; flex-direction: column; gap: 3px; } #tmm .tm-deps .lb { font-size: calc(10.5px * var(--fs)); color: var(--muted); margin-top: 4px; }
#tmm .tm-deps .dep { all: unset; cursor: pointer; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 8px; align-items: center; padding: 2px 6px; margin: 0 -6px; border-radius: 5px; }
#tmm .tm-deps .dep:hover { background: rgba(148,163,184,.08); } #tmm .tm-deps .id { font: calc(11px * var(--fs)) "JetBrains Mono", monospace; color: #a78bfa; }
#tmm .tm-deps .tt { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #b8c4d8; }
#tmm .tm-mach details { border-radius: 6px; } #tmm .tm-mach summary { cursor: pointer; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; list-style: none; padding: 2px 0; }
#tmm .tm-mach summary::-webkit-details-marker { display: none; } #tmm .tm-mach summary .s { color: #fbbf24; } #tmm .tm-mach summary .k { margin-left: auto; }
#tmm .tm-mach ol { margin: 4px 0 6px 15px; padding: 0 0 0 12px; border-left: 1px solid rgba(148,163,184,.15); list-style: none; font-size: calc(11px * var(--fs)); color: #94a3b8; }
#tmm .tm-props { border-collapse: collapse; width: 100%; } #tmm .tm-props td { padding: 3px 10px 3px 0; vertical-align: top; } #tmm .tm-props td:first-child { color: var(--muted); width: 74px; white-space: nowrap; }
#tmm .chips { display: flex; flex-wrap: wrap; gap: 4px; } #tmm .chip { padding: 0 7px; border-radius: 999px; background: rgba(148,163,184,.12); font-size: calc(11px * var(--fs)); color: #b8c4d8; } #tmm .chip.nh { background: rgba(251,191,36,.16); color: #fbbf24; }
#tmm .tm-sec.shut { gap: 0; }
/* Connect a tracker */
#tmm .tm-modal.tk { width: clamp(680px, 54vw, 1040px); height: auto; max-height: 86vh; overflow-y: auto; padding: 18px 24px 22px; gap: 10px; }
#tmm .tk-head { display: flex; align-items: center; justify-content: space-between; } #tmm .tk-head h2 { margin: 0; font-size: calc(16px * var(--fs)); font-weight: 500; }
#tmm .tk p { margin: 0; line-height: 1.55; } #tmm .tk code { font-size: .95em; color: #b8c4d8; }
#tmm .tk .found { padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(167,139,250,.5); background: rgba(167,139,250,.10); line-height: 1.5; display: flex; flex-direction: column; gap: 6px; }
#tmm .tk-list { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
#tmm .tk-list .tk { border: 1px solid rgba(148,163,184,.16); border-radius: 8px; } #tmm .tk-list .tk.on { border-color: rgba(167,139,250,.45); background: rgba(167,139,250,.04); }
#tmm .tk-row { all: unset; cursor: pointer; box-sizing: border-box; width: 100%; display: grid; grid-template-columns: 12px auto auto minmax(0, 1fr); align-items: baseline; gap: 4px 10px; padding: 9px 12px; }
#tmm .tk-row:hover b { color: #fff; } #tmm .tk-row .chev { color: var(--muted); } #tmm .tk-row b { font-weight: 500; white-space: nowrap; }
#tmm .tk-row .badge { font-size: calc(10px * var(--fs)); padding: 0 6px; border-radius: 4px; background: rgba(148,163,184,.12); color: #94a3b8; white-space: nowrap; } #tmm .tk-row .badge.connected { background: rgba(52,211,153,.14); color: #34d399; }
#tmm .tk-row .about { color: var(--muted); font-size: calc(11px * var(--fs)); line-height: 1.45; min-width: 0; }
#tmm .tk-body { margin: 0; padding: 0 14px 14px 52px; color: #b8c4d8; display: flex; flex-direction: column; gap: 10px; } #tmm .tk-body li { padding-left: 4px; } #tmm .tk-body li > div:first-child { margin-bottom: 5px; }
#tmm .cmd { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 8px; align-items: start; padding: 7px 8px 7px 12px; border-radius: 6px; background: rgba(2,6,23,.7); }
#tmm .cmd .pr { color: #475569; font: calc(11.5px * var(--fs)) "JetBrains Mono", monospace; line-height: 1.6; } #tmm .cmd code { font-size: calc(11.5px * var(--fs)); line-height: 1.6; color: #dbe4f3; white-space: pre-wrap; overflow-wrap: anywhere; }
#tmm .cmd .tm-copy { background: #0b1220; }
#tmm .tk-body .out { margin-top: 4px; font: calc(11px * var(--fs)) "JetBrains Mono", monospace; color: #34d399; overflow-wrap: anywhere; }
/* narrow windows: one column, the rail first so live state stays on top */
@media (max-width: 1100px) {
  #tmm .tm-modal { width: calc(100vw - 24px); height: calc(100vh - 24px); }
  #tmm .tm-body { display: flex; flex-direction: column-reverse; overflow-y: auto; } #tmm .tm-col { overflow: visible !important; } #tmm .tm-rail { border-left: 0; border-bottom: 1px solid rgba(148,163,184,.10); }
}
.tm-toast { position: fixed; z-index: 80; left: 50%; bottom: 60px; transform: translateX(-50%); padding: 8px 14px; border-radius: 8px; background: #0b1220; border: 1px solid rgba(52,211,153,.5); color: #34d399; font: calc(12px * var(--fs)) Inter, system-ui, sans-serif; box-shadow: 0 10px 30px rgba(0,0,0,.5); transition: opacity .3s; }
.tm-toast.out { opacity: 0; }
#tm-bar { position: fixed; z-index: 70; left: 50%; bottom: 10px; transform: translateX(-50%); display: flex; gap: 14px; align-items: center; padding: 5px 10px; border-radius: 8px; background: rgba(11,18,32,.92); border: 1px dashed rgba(167,139,250,.45); font: 11px Inter, system-ui, sans-serif; color: #94a3b8; }
#tm-bar b { color: #c4b5fd; font-weight: 500; } #tm-bar .seg { display: flex; gap: 2px; align-items: center; } #tm-bar .lb { margin-right: 4px; }
#tm-bar button { all: unset; cursor: pointer; padding: 2px 7px; border-radius: 5px; } #tm-bar button:hover { color: #dbe4f3; } #tm-bar button.on { background: rgba(167,139,250,.2); color: #dbe4f3; }
`;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
