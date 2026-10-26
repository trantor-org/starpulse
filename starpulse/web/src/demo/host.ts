// The demo's presence on the page, without the demo tree. A served page reads only this module; an embedded fixture or `?demo`
// loads `demo.ts` on demand and registers its server here before the stream opens.

/** What `apiFetch` and `openStream` need from a demo page's server; the class that builds it lives in `demo.ts`. */
export interface DemoServerHandle {
  fetch(url: string, init?: RequestInit): Promise<Response>;
  readonly snapshot: unknown;
  subscribe(fn: (snap: unknown) => void): () => void;
  start(): void;
  stop(): void;
}

let server: DemoServerHandle | null = null;

/** The snapshot a self-contained demo page embeds as `window.__FLOW_FIXTURE__`, null on a served page. */
export const embedded = (): object | null => (globalThis as { __FLOW_FIXTURE__?: object }).__FLOW_FIXTURE__ ?? null;

/** The page's one DemoServer once `demo.ts` has installed it, else null: a served page asks starpulse.runtime.server. */
export const demoServer = (): DemoServerHandle | null => server;

/** Registers the server `ensureDemoServer` built, or clears it in a test. */
export const setDemoServer = (next: DemoServerHandle | null): void => {
  server = next;
};
