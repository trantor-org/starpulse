// Every machine's tasks and the runs instances' workflows, pushed by /api/events: a snapshot on every connect, then one delta per change.

import { demoServer, type DemoServerHandle } from "../demo/host";
import { playLink } from "../demo/linkDemo";
import type { AutopilotStatus, Delta, LedgerRow, Settled, Snapshot } from ".";
import { keep } from "./same";

export { embedded } from "../demo/host";

/** The longest the page waits before it reopens a connection that has not opened since it dropped. */
export const RETRY_CAP_MS = 3000;
/** How long a connection stays down before the page calls it lost; it goes on retrying. */
export const LOST_MS = 20_000;
/** The wait before the `attempt`th reopen of a dropped connection: none for the first, then 250 ms doubling to the cap. */
export const retryWait = (attempt: number) => (attempt === 0 ? 0 : Math.min(RETRY_CAP_MS, 250 * 2 ** (attempt - 1)));
/** The stream, asking for each snapshot as `ref <path>`: a browser reads a long event on its main thread, a fetched body off it. */
const EVENTS = "/api/events?snapshot=ref";
const OPEN = 1;
const CLOSED = 2;

/** One event's rows with `changed` replacing the same keys or joining by time (newest first); every other row stays as it was. */
export function foldRows(rows: LedgerRow[], changed: LedgerRow[]): LedgerRow[] {
  const replaced = new Map(changed.map((row) => [row.key, row]));
  const held = new Set(rows.map((row) => row.key));
  const kept = rows.map((row) => replaced.get(row.key) ?? row);
  const added = changed.filter((row) => !held.has(row.key));
  return added.length ? [...kept, ...added].sort((x, y) => y.at - x.at) : kept;
}

/** The milestone a settled task counts toward in `milestone_done`: the one it completed in, if any. */
const completedIn =(entry: Settled | null | undefined) => (entry?.state === "completed" && entry.milestone ? entry.milestone : null);

/** `done` with a task's settling `was` taken back and `now` counted; `done` itself when neither counts. */
function recount(done: Snapshot["milestone_done"], was: Settled | undefined, now: Settled | null): Snapshot["milestone_done"] {
  const [from, to] = [completedIn(was), completedIn(now)];
  if (from === to) return done;
  const next = { ...done };
  if (from) next[from] = (next[from] ?? 0) - 1;
  if (to) next[to] = (next[to] ?? 0) + 1;
  return next;
}

/** `snap` with one delta folded in; `snap` itself is left as it was. */
export function applyDelta(snap: Snapshot, delta: Delta): Snapshot {
  // a dags, pulls or ledgers delta carries the whole of what it replaces (a ledgers delta the strip and pins, never rows); whatever a delta leaves as it was keeps its old reference, so the page's work follows what changed
  if (delta.kind === "dags") return { ...snap, dags: keep(snap.dags, delta.dags, (d) => d.name), pools: delta.pools ? keep(snap.pools, delta.pools, (p) => p.name) : snap.pools, error: delta.error };
  if (delta.kind === "pulls") return { ...snap, pulls: keep(snap.pulls, delta.pulls) };
  if (delta.kind === "ledgers") return { ...snap, mergeStrip: keep(snap.mergeStrip, delta.mergeStrip), mergePins: keep(snap.mergePins, delta.mergePins) };
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
  return { ...snap, flows, settled, milestone_done: recount(snap.milestone_done, snap.settled[delta.id], delta.settled) };
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

/** What the connection is doing: up, down after the server announced a restart, down with no announcement, or down for LOST_MS. */
export type Link = "live" | "restarting" | "retrying" | "offline";

export interface StreamHandlers {
  /** The sky as it stands: each connect's snapshot, then that snapshot folded with every delta after it, `kind` naming that delta. */
  snapshot(sky: Snapshot, kind?: Delta["kind"]): void;
  /** Whether the connection is up. */
  live(on: boolean): void;
  /** What the connection is doing, each time that changes: `restarting` from the server's announcement, even while the connection is still open. */
  link?(state: Link): void;
  /** The server named a page build other than the one the page holds, once per such build, once that server has read its board. */
  build?(id: string): void;
  /** Autopilot capacity and next pick: not part of the snapshot; the Kanban strip applies each body. */
  autopilot?(status: AutopilotStatus): void;
  /** Orbit level aggregates; not part of the snapshot. */
  level?(body: unknown): void;
}

/**
 * One EventSource on /api/events, or on a self-contained demo page its DemoServer, followed with no connection at all. The server opens
 * each connection with a fresh snapshot, so a reconnect resyncs. A browser waits seconds before it retries a source of its own, so the
 * page closes a dropped connection and opens a new one at once, then after 250 ms, 500 ms and so on up to RETRY_CAP_MS.
 */
export function openStream(
  handlers: StreamHandlers,
  open: (url: string) => EventSource = (url) => new EventSource(url),
  demo: DemoServerHandle | null = demoServer(),
  early: EarlyStream | null = takeEarly(),
): { close(): void } {
  if (demo) {
    handlers.live(true);
    handlers.link?.("live");
    const stopLink = playLink(handlers, new URLSearchParams(globalThis.location?.search ?? "").get("link"), LOST_MS);
    const push = (snap: unknown) => handlers.snapshot(snap as Snapshot);
    push(demo.snapshot);
    const off = demo.subscribe(push);
    demo.start();
    return {
      close() {
        stopLink();
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
    tell();
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

  let showing: Link | null = null;
  const show = (state: Link) => {
    if (state === showing) return;
    showing = state;
    handlers.link?.(state);
  };
  /** The connection opened, as far as the server's page build and restart go: the next drop starts over. */
  let attempts = 0;
  let announced = false;
  let lost: ReturnType<typeof setTimeout> | undefined;
  const goesLost = () => void (lost ??= setTimeout(() => show("offline"), LOST_MS));
  const up = () => {
    clearTimeout(lost);
    lost = undefined;
    attempts = 0;
    announced = false;
    show("live");
    handlers.live(true);
  };
  const drop = () => {
    handlers.live(false);
    if (showing !== "offline") show(announced ? "restarting" : "retrying");
    goesLost();
    clearTimeout(timer);
    if (!stopped) timer = setTimeout(() => connect(), retryWait(attempts++));
  };
  /** The page build the page's own first connection named, which the page was loaded from. */
  let own: string | null = null;
  let told: string | null = null;
  /** A build the page has not reported yet because its server was still reading its board: a page reloaded onto it then would draw the partial Board. */
  let pending: string | null = null;
  const tell = () => {
    if (pending === null || state?.reading) return;
    handlers.build?.((told = pending));
    pending = null;
  };

  const connect = (adopt: EarlyStream | null = null) => {
    const src = adopt?.src ?? open(EVENTS);
    source = src;
    waiting = null;
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
            drop();
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
    src.addEventListener("autopilot", later((e) => {
      handlers.autopilot?.(JSON.parse((e as MessageEvent<string>).data) as AutopilotStatus);
    }));
    src.addEventListener("level", later((e) => {
      handlers.level?.(JSON.parse((e as MessageEvent<string>).data));
    }));
    src.addEventListener("restarting", () => {
      announced = true;
      show("restarting");
      goesLost();
    });
    src.addEventListener(
      "build",
      later((e) => {
        const id = (JSON.parse((e as MessageEvent<string>).data) as { id: string }).id;
        if (own === null) own = id;
        else if (id !== own && id !== told) {
          pending = id;
          tell();
        }
      }),
    );
    src.onopen = up;
    src.onerror = () => {
      src.close(); // not the browser's own retry, which waits seconds
      drop();
    };
    if (!adopt) return;
    // what the connection did before the page listened: the events in order through the listeners just added, then its open or its end
    adopt.adopted = true;
    for (const { type, data } of adopt.events) src.dispatchEvent(new MessageEvent(type, { data }));
    adopt.events.length = 0;
    if (src.readyState === OPEN) up();
    else if (src.readyState === CLOSED) src.onerror?.(new Event("error"));
  };

  connect(demo ? null : early);
  return {
    close() {
      stopped = true;
      clearTimeout(timer);
      clearTimeout(lost);
      source?.close();
    },
  };
}
