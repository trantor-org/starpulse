// Every machine's tasks and the runs instances' workflows, pushed by /api/events: a snapshot on every connect, then one delta per change.

import { demoServer, type DemoServer } from "./demo";
import type { Delta, Snapshot } from "./types";

export { embedded } from "./demo";

/** How long after the browser gives a connection up before the page opens a fresh one. */
export const RETRY_MS = 3000;
const CLOSED = 2;

/** `snap` with one delta folded in; `snap` itself is left as it was. */
export function applyDelta(snap: Snapshot, delta: Delta): Snapshot {
  if (delta.kind === "dags") return { ...snap, dags: delta.dags, pools: delta.pools ?? snap.pools, error: delta.error };
  if (delta.kind === "pulls") return { ...snap, pulls: delta.pulls };
  if (delta.kind === "suns") return { ...snap, suns: delta.suns };
  if (delta.kind === "claim") return { ...snap, claims: { ...snap.claims, [delta.task]: { reason: delta.reason, at: delta.at } } };
  if (delta.kind === "move") {
    const flows = snap.flows.map((flow) => {
      if (flow.name !== delta.flow) return flow;
      const at = flow.agents.findIndex((a) => a.id === delta.id);
      const agents = at < 0 ? [...flow.agents, delta.agent] : flow.agents.map((a, i) => (i === at ? delta.agent : a));
      return { ...flow, agents };
    });
    return { ...snap, flows };
  }
  const flows = snap.flows.map((flow) => {
    if (flow.name !== "board") return flow;
    const rest = flow.agents.filter((a) => a.id !== delta.id);
    const at = flow.agents.findIndex((a) => a.id === delta.id);
    if (delta.agent === null) return { ...flow, agents: rest };
    const agents = at < 0 ? [...rest, delta.agent] : flow.agents.map((a, i) => (i === at ? delta.agent! : a));
    return { ...flow, agents };
  });
  const settled = { ...snap.settled };
  if (delta.settled === null) delete settled[delta.id];
  else settled[delta.id] = delta.settled;
  return { ...snap, flows, settled };
}

export interface StreamHandlers {
  /** The sky as it stands: each connect's snapshot, then that snapshot folded with every delta after it. */
  snapshot(sky: Snapshot): void;
  /** Whether the connection is up. */
  live(on: boolean): void;
}

/**
 * One EventSource on /api/events, or on a self-contained demo page its DemoServer, followed with no connection at all. The browser retries a dropped connection on
 * its own and the server opens each with a fresh snapshot, so a reconnect
 * resyncs; when the browser gives a connection up the page opens a new one.
 */
export function openStream(
  handlers: StreamHandlers,
  open: (url: string) => EventSource = (url) => new EventSource(url),
  demo: DemoServer | null = demoServer(),
): { close(): void } {
  if (demo) {
    handlers.live(true);
    handlers.snapshot(demo.snapshot);
    const off = demo.subscribe(handlers.snapshot);
    demo.start();
    return {
      close() {
        off();
        demo.stop();
      },
    };
  }
  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  let state: Snapshot | null = null;
  /** A restarted server's partial Board is not handed over once the page has drawn one: the page keeps its own until the server has read its board. */
  let shown = false;
  const hand = () => {
    if (shown && state!.reading) return;
    shown = true;
    handlers.snapshot(state!);
  };

  const fold = (delta: Delta) => {
    if (!state) return; // a delta means nothing before the snapshot it extends
    state = applyDelta(state, delta);
    hand();
  };

  const connect = () => {
    const src = open("/api/events");
    source = src;
    src.addEventListener("snapshot", (e) => {
      state = JSON.parse((e as MessageEvent<string>).data) as Snapshot;
      hand();
    });
    src.addEventListener("task", (e) =>
      fold({ kind: "task", ...JSON.parse((e as MessageEvent<string>).data) }),
    );
    src.addEventListener("move", (e) =>
      fold({ kind: "move", ...JSON.parse((e as MessageEvent<string>).data) }),
    );
    src.addEventListener("dags", (e) =>
      fold({ kind: "dags", ...JSON.parse((e as MessageEvent<string>).data) }),
    );
    src.addEventListener("pulls", (e) =>
      fold({ kind: "pulls", ...JSON.parse((e as MessageEvent<string>).data) }),
    );
    src.addEventListener("suns", (e) =>
      fold({ kind: "suns", ...JSON.parse((e as MessageEvent<string>).data) }),
    );
    src.addEventListener("claim", (e) =>
      fold({ kind: "claim", ...JSON.parse((e as MessageEvent<string>).data) }),
    );
    src.onopen = () => handlers.live(true);
    src.onerror = () => {
      handlers.live(false);
      if (src.readyState === CLOSED && !stopped) timer = setTimeout(connect, RETRY_MS);
    };
  };

  connect();
  return {
    close() {
      stopped = true;
      clearTimeout(timer);
      source?.close();
    },
  };
}
