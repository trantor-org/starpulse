// The element sheet's script: it draws the palette from the stylesheet's own `:root` tokens and paints the Star Map's two bodies.
// ROLES names what each token is for. ci/test_element_sheet.py fails when a token in style.css has no role here, or a role names no token.
const ROLES = [
  ["Text and lines", {
    "--ink": "body text, the brightest type",
    "--ink-hi": "emphasis: the hovered card's chain outline",
    "--ink-2": "quiet button and chip text",
    "--ink-3": "card, modal and menu body text",
    "--slate": "labels and quiet type; the base of every border and quiet fill (.06 fill, .10 hairline, .18 border, .25 strong)",
    "--muted": "meta text, counts, headings",
    "--dim": "hints and row numbers",
    "--faint": "placeholders and disabled text",
    "--ghost": "empty states and level captions",
    "--track": "the faintest rule",
  }],
  ["Near-duplicate greys", {
    "--slate-2": "kept at its exact value; a design pass folds it into --slate",
    "--slate-3": "kept at its exact value; a design pass folds it into --slate",
    "--slate-4": "kept at its exact value; a design pass folds it into --slate",
  }],
  ["Surfaces, darkest first", {
    "--bg0": "the page",
    "--bg1": "the page glow, top left",
    "--bg2": "the second page glow",
    "--surface": "card, panel, menu and modal fill, drawn at 85-99% over the page",
    "--pop": "a popover's solid fill",
    "--stack": "the card edges peeking under a folded Waiting stack",
    "--glass": "the rail and navigator glass",
    "--field": "an input's fill",
    "--sticky": "a sticky header's fill",
    "--veil": "the discard question's veil",
    "--code": "a code block's fill",
    "--scrim": "the dim behind a modal",
    "--shadow": "the base of every drop shadow",
    "--white": "code inside a refusal",
  }],
  ["Status", {
    "--ok": "checks pass, done, start, saved",
    "--ok-hi": "ok on hover; the start button's fill",
    "--ok-text": "type on an ok tint",
    "--ok-ink": "type on a solid ok fill",
    "--run": "pending, running, in progress, a guard",
    "--run-text": "type on a run tint",
    "--fail": "failing, needs attention, a refusal",
    "--fail-text": "type on a fail tint",
    "--fail-hi": "a refusal's emphasis",
    "--fail-bg": "a refusal's fill",
    "--danger": "a destructive action: archive",
    "--danger-text": "type on a danger tint",
    "--danger-hi": "the destructive button's type",
    "--agent": "merged, agent, review, links, focus",
    "--agent-text": "agent type: the machine name, a clear link",
    "--agent-hi": "type on an agent tint",
    "--agent-deep": "the deep agent tier",
    "--agent-soft": "type on the orbit card's sign-in button",
    "--hold": "holds, the tasks they block and a Waiting stack's spine",
    "--hold-text": "type on a hold tint: a waits-on line",
    "--hold-hi": "a stack count's type",
    "--waits": "a task's waits-on chain, a size label",
    "--waits-text": "type on a waits tint",
    "--ready": "the Ready lane",
    "--released": "a released session",
  }],
  ["Glyphs", {
    "--ok-check": "the checked box's tick, a data URI that cannot read a custom property",
  }],
];

const tokens = Object.fromEntries(ROLES.flatMap(([, group]) => Object.entries(group)));

/** Every `:root` custom property the loaded stylesheets declare, as name → value as written. */
function declared() {
  const found = {};
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch { continue; } // a file:// stylesheet is unreadable: serve the checkout over http
    for (const rule of rules) {
      if (rule.selectorText !== ":root") continue;
      for (const name of rule.style) if (name.startsWith("--")) found[name] = rule.style.getPropertyValue(name).trim();
    }
  }
  return found;
}

function palette(into) {
  const found = declared();
  if (!Object.keys(found).length) {
    into.textContent = "The stylesheet could not be read: open this page over http (python -m http.server from the repository root), not file://.";
    return;
  }
  for (const [title, group] of ROLES) {
    const h = document.createElement("h3");
    h.textContent = title;
    const grid = document.createElement("div");
    grid.className = "swatches";
    for (const name of Object.keys(group)) {
      const tick = name === "--ok-check";
      const el = document.createElement("div");
      el.className = "swatch";
      el.innerHTML = `<i class="well${tick ? " tick" : ""}" style="${tick ? "background-image" : "background"}: var(${name})"></i><b></b><code></code><span></span>`;
      el.querySelector("b").textContent = name;
      el.querySelector("code").textContent = tick ? "url(data:image/svg+xml…)" : found[name] ?? "not declared";
      el.querySelector("span").textContent = group[name];
      grid.append(el);
    }
    into.append(h, grid);
  }
  const extra = Object.keys(found).filter((n) => !(n in tokens) && !["--rail", "--nav", "--nav-fold", "--fs"].includes(n));
  if (extra.length) {
    const p = document.createElement("p");
    p.className = "warn";
    p.textContent = `Declared in style.css with no role in elements.js: ${extra.join(", ")}`;
    into.append(p);
  }
}

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const rgba = (hex, a) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
};

/** The Star Map's bodies as renderer.ts draws them (drawSun, hole), in the page's own tokens. */
function bodies() {
  const draw = (id, fn) => {
    const c = document.getElementById(id), cx = c.getContext("2d"), s = devicePixelRatio || 1;
    c.width = c.clientWidth * s;
    c.height = c.clientHeight * s;
    cx.scale(s, s);
    fn(cx, c.clientWidth / 2, c.clientHeight / 2);
  };
  const R = 34;
  draw("sun", (cx, x, y) => {
    const col = css("--run");
    const glow = cx.createRadialGradient(x, y, 0, x, y, R + 5 * 34);
    glow.addColorStop(0, rgba(col, 0.55));
    glow.addColorStop(0.25, rgba(col, 0.2));
    glow.addColorStop(1, rgba(col, 0));
    cx.fillStyle = glow;
    cx.beginPath();
    cx.arc(x, y, R + 5 * 34, 0, Math.PI * 2);
    cx.fill();
    const core = cx.createRadialGradient(x, y, 0, x, y, R);
    core.addColorStop(0, css("--agent-hi"));
    core.addColorStop(0.5, rgba(col, 0.95));
    core.addColorStop(1, rgba(col, 0.6));
    cx.fillStyle = core;
    cx.beginPath();
    cx.arc(x, y, R, 0, Math.PI * 2);
    cx.fill();
  });
  draw("hole", (cx, x, y) => {
    const col = css("--ok"), rs = R * 0.6;
    const g = cx.createRadialGradient(x, y, rs, x, y, R);
    g.addColorStop(0, rgba(col, 0.28));
    g.addColorStop(1, rgba(col, 0));
    cx.fillStyle = g;
    cx.beginPath();
    cx.arc(x, y, R, 0, Math.PI * 2);
    cx.fill();
    cx.fillStyle = css("--bg0");
    cx.beginPath();
    cx.arc(x, y, rs, 0, Math.PI * 2);
    cx.fill();
    for (const [r, a, w] of [[rs, 0.85, 1.4], [R, 0.14, 1]]) {
      cx.strokeStyle = rgba(col, a);
      cx.lineWidth = w;
      cx.beginPath();
      cx.arc(x, y, r, 0, Math.PI * 2);
      cx.stroke();
    }
  });
}

palette(document.getElementById("palette"));
bodies();
