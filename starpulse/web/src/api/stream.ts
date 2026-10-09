// Every machine's tasks and the runs instances' workflows, pushed by /api/events: a snapshot on every connect, then one delta per change.

import { demoServer, type DemoServer } from "../demo/demo";
import type { Delta, LedgerRow, Snapshot } from ".";
import { keep } from "./same";

export { embedded } from "../demo/demo";

/** How long after the browser gives a connection up before the page opens a fresh one. */
export const RETRY_MS = 3000;
/** The stream, asking for each snapshot as `ref <path>`: a browser reads a long event on its main thread, a fetched body off it. */
const EVENTS = "/api/events?snapshot=ref";
const OPEN = 1;
const CLOSED = 2;

/** One event's rows with `changed` replacing the same keys or joining by time (newest first), and the `gone` keys dropped; every other row stays as it was. */
function foldRows(rows: LedgerRow[], changed: LedgerRow[], gone: string[]): LedgerRow[] {
  const replaced = new Map(changed.map((row) => [row.key, row]));
  const left = new Set(gone);
  const held = new Set(rows.map((row) => row.key));
  const kept = rows.filter((row) => !left.has(row.key)).map((row) => replaced.get(row.key) ?? row);
  const added = changed.filter((row) => !held.has(row.key));
  return added.length ? [...kept, ...added].sort((x, y) => y.at - x.at) : kept;
}

/** The ledgers with a delta's changed rows and gone keys folded in; an event the delta does not name keeps its array. */
function foldLedgers(ledgers: Snapshot["ledgers"], delta: { ledgers: Record<string, LedgerRow[]>; gone: Record<string, string[]> }) {
  const next = { ...ledgers };
  for (const event of new Set([...Object.keys(delta.ledgers), ...Object.keys(delta.gone)]))
    next[event] = foldRows(ledgers?.[event] ?? [], delta.ledgers[event] ?? [], delta.gone[event] ?? []);
  return next;
}

/** `snap` with one delta folded in; `snap` itself is left as it was. */
export function applyDelta(snap: Snapshot, delta: Delta): Snapshot {
  // a dags or pulls delta carries the whole of what it replaces, a ledgers delta only the rows that changed or left; whatever a delta leaves as it was keeps its old reference, so the page's work follows what changed
  if (delta.kind === "dags") return { ...snap, dags: keep(snap.dags, delta.dags, (d) => d.name), pools: delta.pools ? keep(snap.pools, delta.pools, (p) => p.name) : snap.pools, error: delta.error };
  if (delta.kind === "pulls") return { ...snap, pulls: keep(snap.pulls, delta.pulls) };
  if (delta.kind === "ledgers") return { ...snap, ledgers: foldLedgers(snap.ledgers, delta), mergeStrip: keep(snap.mergeStrip, delta.mergeStrip), mergePins: keep(snap.mergePins, delta.mergePins) };
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

/**
 * The connection index.html opens before the bundle loads, so the server's snapshot is already on its way (or here) while the bundle
 * is fetched and run. It holds the events that arrived before the page listened, as `{ type, data }`, in order.
 */
export interface EarlyStream {
  src: EventSource;
  events: { type: string; data: string }[];
  /** Set once the page listens itself, so index.html stops holding events. */
  adopted?: boolean;
  /** The answer to each snapshot body index.html asked for, by its path. */
  bodies?: Record<string, Promise<Response>>;
}

/** The page's one early connection, handed over once: a reconnect opens its own. */
function takeEarly(): EarlyStream | null {
  const w = globalThis as { __earlyStream?: EarlyStream };
  const early = w.__earlyStream ?? null;
  delete w.__earlyStream;
  return early;
}

export interface StreamHandlers {
  /** The sky as it stands: each connect's snapshot, then that snapshot folded with every delta after it, `kind` naming that delta. */
  snapshot(sky: Snapshot, kind?: Delta["kind"]): void;
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
  early: EarlyStream | null = takeEarly(),
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
  const hand = (kind?: Delta["kind"]) => {
    if (shown && state!.reading) return;
    shown = true;
    handlers.snapshot(state!, kind);
  };

  /** While a snapshot's body is read, the events after it, run in order once it is the page's state. */
  let waiting: (() => void)[] | null = null;
  const take = (snap: Snapshot) => {
    waiting = null;
    state = snap;
    held.clear(); // the snapshot is the page's truth again, so what the next event says is news
    hand();
  };
  const later = (fn: (e: Event) => void) => (e: Event) => void (waiting ? waiting.push(() => fn(e)) : fn(e));

  const fold = (delta: Delta) => {
    if (!state) return; // a delta means nothing before the snapshot it extends
    state = applyDelta(state, delta);
    hand(delta.kind);
  };

  /** The last body of each event that replaces a whole section: the server resends the DAGs, pulls and Ledger on any change, often with nothing new in them. */
  const held = new Map<string, string>();
  const replacing = (kind: "dags" | "pulls" | "ledgers") => (e: Event) => {
    const body = (e as MessageEvent<string>).data;
    if (held.get(kind) === body) return;
    held.set(kind, body);
    fold({ kind, ...JSON.parse(body) });
  };

  const connect = (adopt: EarlyStream | null = null) => {
    const src = adopt?.src ?? open(EVENTS);
    source = src;
    waiting = null;
    const reopen = () => {
      if (!stopped) timer = setTimeout(() => connect(), RETRY_MS);
    };
    src.addEventListener("snapshot", (e) => {
      const data = (e as MessageEvent<string>).data;
      if (!data.startsWith("ref ")) return take(JSON.parse(data) as Snapshot);
      const path = data.slice(4);
      const mine: (() => void)[] = (waiting = []);
      const asked = adopt?.bodies?.[path] ?? fetch(path);
      if (adopt?.bodies) delete adopt.bodies[path];
      asked
        .then((r) => (r.ok ? (r.json() as Promise<Snapshot>) : Promise.reject(new Error(`${path}: ${r.status}`))))
        .then(
          (snap) => {
            if (waiting !== mine) return; // a newer snapshot or connection took its place
            take(snap);
            for (const run of mine) run();
          },
          () => {
            if (waiting !== mine) return;
            waiting = null;
            src.close(); // the server holds no body by that name now: a fresh connection sends a fresh snapshot
            handlers.live(false);
            reopen();
          },
        );
    });
    src.addEventListener("task", later((e) =>
      fold({ kind: "task", ...JSON.parse((e as MessageEvent<string>).data) }),
    ));
    src.addEventListener("move", later((e) =>
      fold({ kind: "move", ...JSON.parse((e as MessageEvent<string>).data) }),
    ));
    src.addEventListener("dags", later(replacing("dags")));
    src.addEventListener("pulls", later(replacing("pulls")));
    src.addEventListener("ledgers", later(replacing("ledgers")));
    src.addEventListener("claim", later((e) =>
      fold({ kind: "claim", ...JSON.parse((e as MessageEvent<string>).data) }),
    ));
    src.onopen = () => handlers.live(true);
    src.onerror = () => {
      handlers.live(false);
      if (src.readyState === CLOSED) reopen();
    };
    if (!adopt) return;
    // what the connection did before the page listened: the events in order through the listeners just added, then its open or its end
    adopt.adopted = true;
    for (const { type, data } of adopt.events) src.dispatchEvent(new MessageEvent(type, { data }));
    adopt.events.length = 0;
    if (src.readyState === OPEN) handlers.live(true);
    else if (src.readyState === CLOSED) src.onerror?.(new Event("error"));
  };

  connect(demo ? null : early);
  return {
    close() {
      stopped = true;
      clearTimeout(timer);
      source?.close();
    },
  };
}
