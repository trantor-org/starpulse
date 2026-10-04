// `?demo`: walk random legal transitions in random flows so every section moves.
import type { Snapshot } from "./types";

let demoN = 0;

export function demoStep(prev: Snapshot, random = Math.random): Snapshot {
  const snap = structuredClone(prev);
  const f = snap.flows[Math.floor(random() * snap.flows.length)];
  if (!f) return stepDags(snap, random);
  const trans = f.machine.transitions;
  const init = f.machine.states.find((s) => s.initial)?.id ?? f.machine.states[0].id;
  const finals = new Set(f.machine.states.filter((s) => s.final).map((s) => s.id));
  const now = Date.now() / 1000;
  if (f.name === "board") {
    const pool = f.agents.filter((a) => a.state !== "done" || random() < 0.1);
    const ag = pool[Math.floor(random() * f.agents.length * 0.9)] ?? f.agents[0];
    const outs = ag ? trans.filter((e) => e.source === ag.state && e.target !== e.source) : [];
    if (ag && outs.length) {
      const e = outs[Math.floor(random() * outs.length)];
      if (finals.has(e.target)) {
        f.agents = f.agents.filter((a) => a !== ag);
        snap.settled[ag.id] = e.target;
      } else ag.state = e.target;
    }
  } else {
    if (!f.agents.length || (f.agents.length < 6 && random() < 0.25))
      f.agents.push({
        id: `DEMO-${100 + ++demoN}`, task: `DEMO-${100 + demoN}`, title: "demo", model: ["@agent-deep-high", "@agent-standard-high", ""][demoN % 3],
        state: init, steps: 0, trail: [], active: now,
      });
    const ag = f.agents[Math.floor(random() * f.agents.length)];
    const outs = trans.filter((e) => e.source === ag.state);
    if (outs.length && !finals.has(ag.state)) {
      const e = outs[Math.floor(random() * outs.length)];
      ag.state = e.target;
      ag.steps = (ag.steps ?? 0) + 1;
      (ag.trail ??= []).push({ state: e.target, event: e.event, at: now });
      ag.active = now;
    } else f.agents = f.agents.filter((a) => a !== ag);
  }
  return stepDags(snap, random);
}

function stepDags(snap: Snapshot, random: () => number): Snapshot {
  if (snap.dags.length && random() < 0.3) {
    const d = snap.dags[Math.floor(random() * snap.dags.length)];
    d.status = d.status === "running" ? (random() < 0.85 ? "succeeded" : "failed") : d.status === "queued" ? "running" : "queued";
    if (d.status === "queued") d.runId += "+";
  }
  return snap;
}
