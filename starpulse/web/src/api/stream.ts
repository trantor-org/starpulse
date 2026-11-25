// Every machine's tasks and the runs instances' workflows, pushed by /api/events: a snapshot on every connect, then one delta per change.

import type { Delta, LedgerRow, Settled, Snapshot } from ".";
import { browserCache, type SnapshotCache } from "./savedSnapshot";
import { apiFetch } from "./apiFetch";
import { openHealth, type Health, type Watch } from "./health";
import { keep, same } from "./same";
import { decodeMove, decodeSnapshot, intern } from "./trails";
import type { Snapshot as WireSnapshot } from "./types.gen";

/** The longest the page waits before it reopens a connection that has not opened since it dropped. */
export const RETRY_CAP_MS = 3000;
/** How long a connection stays down before the page calls it lost; it goes on retrying. */
export const LOST_MS = 20_000;
/** The longest a snapshot waits to be written to browser storage: a burst of deltas is written once. */
export const KEEP_MS = 1000;
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

/** The milestone a settled task counts toward in `milestone_done`: the one it completed in (settled in the `final` State), if any. */
const completedIn = (final: string | null | undefined, entry: Settled | null | undefined) =>
  (final && entry?.state === final && entry.milestone ? entry.milestone : null);

/** `done` with a task's settling `was` taken back and `now` counted; `done` itself when neither counts. */
function recount(done: Snapshot["milestone_done"], final: string | null | undefined, was: Settled | undefined, now: Settled | null): Snapshot["milestone_done"] {
  const [from, to] = [completedIn(final, was), completedIn(final, now)];
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
    // the server sends a move twice, and a harness, build or deliver place again whenever its session writes, often with nothing new: that is no change, so the page keeps its snapshot and draws nothing
    const held = snap.flows.find((flow) => flow.name === delta.machine)?.agents.find((a) => a.id === delta.id);
    if (same(held, delta.agent)) return snap;
    const flows = snap.flows.map((flow) => {
      if (flow.name !== delta.machine) return flow;
      const at = flow.agents.findIndex((a) => a.id === delta.id);
      const agents = at < 0 ? [...flow.agents, delta.agent] : flow.agents.map((a, i) => (i === at ? delta.agent : a));
      return { ...flow, agents, names: intern(flow.names, delta.names) };
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
  const archived = delta.archived_today == null ? {} : { archived_today: delta.archived_today };
  return { ...snap, ...archived, flows, settled, milestone_done: recount(snap.milestone_done, snap.roles?.final, snap.settled[delta.id], delta.settled) };
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

/**
 * What the connection is doing: up, down after the server announced a restart, down with no announcement, or down for LOST_MS. `stale`
 * is the page showing a Board the server has not confirmed: the one kept from the last load before the server answers, the one it
 * held while the server it reconnected to is still reading its own, or the one no Board writer is folding (the server's `stale` event,
 * cleared by the next change).
 */
export type Link = "live" | "restarting" | "retrying" | "offline" | "stale";

export interface StreamHandlers {
  /** The sky as it stands: each connect's snapshot, then that snapshot folded with every delta after it, `kind` naming that delta. */
  snapshot(sky: Snapshot, kind?: Delta["kind"]): void;
  /** Whether the connection is up. */
  live(on: boolean): void;
  /** What the connection is doing, each time that changes: `restarting` from the server's announcement, even while the connection is still open. */
  link?(state: Link): void;
  /** The server named a page build other than the one the page holds, once per such build, once that server has read its board. */
  build?(id: string): void;
  /** How many seconds the server's clock is ahead of the page's, from the server's time on each health event. */
  clock?(skew: number): void;
}

/**
 * One EventSource on /api/events, and beside it one health subscription (`watch`) that says whether the server announced a restart,
 * whether it is still reading its board, which page build it serves and what time it is. The server opens
 * each connection with a fresh snapshot, so a reconnect resyncs. The snapshot the page holds is kept in `kept` (browser storage), and a
 * page that loads while the server is down draws that one, marked `stale`, until the server's own arrives; null keeps and restores nothing. A browser waits seconds before it retries a source of its own, so the
 * page closes a dropped connection and opens a new one at once, then after 250 ms, 500 ms and so on up to RETRY_CAP_MS.
 */
export function openStream(
  handlers: StreamHandlers,
  open: (url: string) => EventSource = (url) => new EventSource(url),
  early: EarlyStream | null = takeEarly(),
  kept: SnapshotCache | null = browserCache(),
  watch: Watch = openHealth,
): { close(): void } {
  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  let state: Snapshot | null = null;
  /** A restarted server's partial Board is not handed over once the page has drawn one: the page keeps its own until the server has read its board. */
  let shown = false;
  /** Set while a snapshot and the events queued behind it fold into one state: each hand is a full pass over the sky, so they cost one. */
  let folding = false;
  /** Set while the Board the page shows predates the connection: the one kept from the last load, or the one held through a drop, until the server's whole one is handed over. */
  let old = false;
  let keeping: ReturnType<typeof setTimeout> | undefined;
  /** Set from a connect until its health says the server's board component is ready: the Board it sends may be partial. */
  let reading = true;
  /** Set when `hand` held a snapshot back for `reading`, so it is handed over once the server has read its board. */
  let withheld = false;
  /** Writes the state as it stands KEEP_MS after the first change since the last write; a browser that refuses it (quota) leaves the page as it was. */
  const keepSoon = () => {
    if (!kept || keeping || reading || !state) return;
    keeping = setTimeout(() => {
      keeping = undefined;
      kept.write(state!).catch(() => {});
    }, KEEP_MS);
  };
  const hand = (kind?: Delta["kind"]) => {
    if (folding) return;
    if (shown && reading) {
      withheld = true;
      return;
    }
    withheld = false;
    shown = true;
    handlers.snapshot(state!, kind);
    keepSoon();
    if (!old || reading) return;
    old = false;
    if (showing === "stale") show("live");
  };

  /** While a snapshot's body is read, the events after it, run in order once it is the page's state. */
  let waiting: (() => void)[] | null = null;
  const take = (snap: WireSnapshot) => {
    waiting = null;
    state = decodeSnapshot(snap);
    held.clear(); // the snapshot is the page's truth again, so what the next event says is news
    hand();
    tell();
  };
  const later = (fn: (e: Event) => void) => (e: Event) => void (waiting ? waiting.push(() => fn(e)) : fn(e));

  const fold = (delta: Delta) => {
    if (!state) return; // a delta means nothing before the snapshot it extends
    const next = applyDelta(state, delta);
    if (next === state) return;
    state = next;
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
    show(old ? "stale" : "live");
    handlers.live(true);
  };
  const drop = () => {
    old ||= shown;
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
    if (pending === null || reading) return;
    handlers.build?.((told = pending));
    pending = null;
  };

  /** What the server's health says: a restart it announced, whether its board is read, the build it serves and its clock. */
  const onHealth = (h: Health) => {
    if (h.restarting && !announced) {
      announced = true;
      show("restarting");
      goesLost();
    }
    reading = h.components.some((c) => c.name === "board" && !c.ready);
    if (h.build !== null) {
      if (own === null) own = h.build;
      else if (h.build !== own && h.build !== told) pending = h.build;
    }
    handlers.clock?.(h.at - Date.now() / 1000);
    if (reading) return;
    if (withheld && !state?.reading) hand(); // a partial Board stays withheld: the snapshot the server publishes as it finishes reading follows
    else if (!old) keepSoon();
    tell();
  };

  let watching: { close(): void } | null = null;
  const connect = (adopt: EarlyStream | null = null) => {
    const src = adopt?.src ?? open(EVENTS);
    source = src;
    waiting = null;
    reading = true;
    let over = false;
    /** Either stream ending ends the connection: the page reopens both, so what the health says is never older than the Board. */
    const end = () => {
      if (over) return;
      over = true;
      src.close(); // not the browser's own retry, which waits seconds
      watching?.close();
      drop();
    };
    watching?.close();
    watching = watch({ health: onHealth, end });
    src.addEventListener("snapshot", (e) => {
      const data = (e as MessageEvent<string>).data;
      if (!data.startsWith("ref ")) return take(JSON.parse(data) as WireSnapshot);
      const path = data.slice(4);
      const mine: (() => void)[] = (waiting = []);
      const asked = adopt?.bodies?.[path] ?? apiFetch(path);
      if (adopt?.bodies) delete adopt.bodies[path];
      asked
        .then((r) => (r.ok ? (r.json() as Promise<WireSnapshot>) : Promise.reject(new Error(`${path}: ${r.status}`))))
        .then(
          (snap) => {
            if (waiting !== mine) return; // a newer snapshot or connection took its place
            folding = true;
            try {
              take(snap);
              for (const run of mine) run();
            } finally {
              folding = false;
              if (state) hand();
            }
          },
          () => {
            if (waiting !== mine) return;
            waiting = null;
            end(); // the server holds no body by that name now: a fresh connection sends a fresh snapshot
          },
        );
    });
    src.addEventListener("task", later((e) =>
      fold({ kind: "task", ...JSON.parse((e as MessageEvent<string>).data) }),
    ));
    src.addEventListener("move", later((e) =>
      fold({ kind: "move", ...decodeMove(JSON.parse((e as MessageEvent<string>).data)) }),
    ));
    src.addEventListener("dags", later(replacing("dags")));
    src.addEventListener("pulls", later(replacing("pulls")));
    src.addEventListener("ledgers", later(replacing("ledgers")));
    src.addEventListener("claim", later((e) =>
      fold({ kind: "claim", ...JSON.parse((e as MessageEvent<string>).data) }),
    ));
    // the page's own build is the one the connection index.html opened named, which health, opened after the page loaded, may not
    src.addEventListener("build", (e) => void (own ??= (JSON.parse((e as MessageEvent<string>).data) as { id: string }).id));
    src.addEventListener("stale", later(() => {
      old = true; // no Board writer folds: the page's Board stays as drawn, marked, until the next change hands over a fresh one
      show("stale");
    }));
    src.onopen = up;
    src.onerror = end;
    if (!adopt) return;
    // what the connection did before the page listened: the events in order through the listeners just added, then its open or its end
    adopt.adopted = true;
    for (const { type, data } of adopt.events) src.dispatchEvent(new MessageEvent(type, { data }));
    adopt.events.length = 0;
    if (src.readyState === OPEN) up();
    else if (src.readyState === CLOSED) src.onerror?.(new Event("error"));
  };

  connect(early);
  // the Board kept from the last load is drawn unless the server's has come first, or its connection has already been heard from
  kept?.read().then(
    (snap) => {
      if (!snap || state || stopped) return;
      [state, shown, old] = [snap, true, true];
      handlers.snapshot(snap);
      show("stale");
    },
    () => {},
  );
  return {
    close() {
      stopped = true;
      clearTimeout(timer);
      clearTimeout(lost);
      clearTimeout(keeping);
      source?.close();
      watching?.close();
    },
  };
}
