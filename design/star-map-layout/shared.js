// Star Map layout mockup: the boards it draws and the curve sampling its layouts are stored in. Loaded by the page (a classic script)
// and by layouts.mjs (Node), so it touches nothing but globalThis.
(function (root) {
  const S = (id, name, flag) => ({ id, name, initial: flag === "i", final: flag === "f" });
  const fan = (a, bs) => bs.map((b) => [a, b]);
  const BASE = {
    states: [S("new", "New", "i"), S("ready", "Ready"), S("waiting", "Waiting"), S("in_progress", "In Progress"), S("review", "Review"), S("needs_attention", "Needs Attention"), S("done", "Done", "f"), S("archived", "Archived", "f")],
    tiers: [["new"], ["ready", "waiting"], ["needs_attention"], ["in_progress"], ["review"], ["done", "archived"]],
    mainLine: ["new", "ready", "in_progress", "review"],
    // the states that hold lifecycle machines, so draw a ring of moons with their names either side
    machines: ["in_progress", "review"],
    transitions: [
      ...fan("new", ["ready", "waiting", "in_progress"]), ...fan("ready", ["in_progress", "waiting", "archived"]), ...fan("waiting", ["ready", "in_progress", "archived"]),
      ...fan("in_progress", ["review", "ready", "waiting", "needs_attention", "done", "archived"]), ...fan("review", ["in_progress", "done", "archived"]),
      ...fan("needs_attention", ["ready", "in_progress", "archived"]),
    ],
  };
  const QA = [["review", "qa"], ["qa", "staging"], ["qa", "done"], ["qa", "in_progress"], ["staging", "done"]], BLOCKED = [["ready", "blocked"], ["blocked", "ready"]];
  const more = (title, states, tiers, transitions, over = {}) => ({ ...BASE, title, states: [...BASE.states, ...states], tiers, transitions: [...BASE.transitions, ...transitions], ...over });
  const boards = {
    base: { ...BASE, title: "Demo board: 8 states in 6 tiers" },
    "third-in-tier": more("A third state in one tier", [S("blocked", "Blocked")], [["new"], ["ready", "waiting", "blocked"], ...BASE.tiers.slice(2)], BLOCKED),
    "two-more-tiers": more("Two more tiers", [S("qa", "QA"), S("staging", "Staging")], [...BASE.tiers.slice(0, 5), ["qa"], ["staging"], BASE.tiers[5]], QA),
    fourteen: more("14 states in 10 tiers",
      [S("qa", "QA"), S("staging", "Staging"), S("triage", "Triage"), S("design", "Design"), S("blocked", "Blocked"), S("cancelled", "Cancelled", "f")],
      [["new"], ["triage"], ["ready", "waiting", "blocked"], ["needs_attention"], ["design"], ["in_progress"], ["review"], ["qa"], ["staging"], ["done", "archived", "cancelled"]],
      [["new", "triage"], ["triage", "ready"], ["ready", "design"], ["design", "in_progress"], ...BLOCKED, ["in_progress", "cancelled"], ...QA]),
    unlisted: more("A state no tier names", [S("blocked", "Blocked")], BASE.tiers, BLOCKED),
    three: {
      ...BASE, title: "3 states in 3 tiers", states: BASE.states.filter((s) => ["new", "in_progress", "done"].includes(s.id)), tiers: [["new"], ["in_progress"], ["done"]],
      mainLine: ["new", "in_progress"], transitions: [["new", "in_progress"], ["in_progress", "done"]],
    },
  };
  /** A board with one state switched off: the state, its transitions and its place in its tier. */
  const without = (b, id) => ({
    ...b, states: b.states.filter((s) => s.id !== id), tiers: b.tiers.map((t) => t.filter((x) => x !== id)).filter((t) => t.length),
    mainLine: b.mainLine.filter((x) => x !== id), transitions: b.transitions.filter(([x, y]) => x !== id && y !== id),
  });
  /** The board a set key names: `board` or `board~state`. */
  const boardOf = (key) => {
    const [name, off] = key.split("~"), b = boards[name];
    return b && (off ? without(b, off) : b);
  };
  /** One path per pair of states joined either way, in the order the board declares them. */
  const pairsOf = (b) => {
    const seen = new Set(), out = [];
    for (const [x, y] of b.transitions) {
      if (x === y || seen.has(`${y}>${x}`) || seen.has(`${x}>${y}`)) continue;
      seen.add(`${x}>${y}`);
      out.push([x, y]);
    }
    return out;
  };
  // A stored route is its kind and its points flat: "l" a polyline, "b" a chain of cubic Beziers (3n + 1 points, as Graphviz and ELK give
  // them), "s" a B-spline through dagre's points with its ends held.
  const cubic = (p, q, r, s, t) => {
    const u = 1 - t, a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t;
    return { x: a * p.x + b * q.x + c * r.x + d * s.x, y: a * p.y + b * q.y + c * r.y + d * s.y };
  };
  const sample = (kind, flat, per = 8) => {
    const P = [];
    for (let i = 0; i + 1 < flat.length; i += 2) P.push({ x: flat[i], y: flat[i + 1] });
    if (kind === "b" && P.length >= 4 && (P.length - 1) % 3 === 0) {
      const out = [P[0]];
      for (let i = 0; i + 3 < P.length; i += 3) for (let j = 1; j <= per; j++) out.push(cubic(P[i], P[i + 1], P[i + 2], P[i + 3], j / per));
      return out;
    }
    if (kind === "s" && P.length > 2) {
      const Q = [P[0], P[0], ...P, P[P.length - 1], P[P.length - 1]], out = [P[0]];
      for (let i = 0; i + 3 < Q.length; i++)
        for (let j = 1; j <= per; j++) {
          const t = j / per, u = 1 - t, a = (u * u * u) / 6, b = (3 * t * t * t - 6 * t * t + 4) / 6, c = (-3 * t * t * t + 3 * t * t + 3 * t + 1) / 6, d = (t * t * t) / 6;
          out.push({ x: a * Q[i].x + b * Q[i + 1].x + c * Q[i + 2].x + d * Q[i + 3].x, y: a * Q[i].y + b * Q[i + 1].y + c * Q[i + 2].y + d * Q[i + 3].y });
        }
      return out;
    }
    return P;
  };
  root.__BOARDS__ = { boards, without, boardOf, pairsOf, sample };
})(globalThis);
