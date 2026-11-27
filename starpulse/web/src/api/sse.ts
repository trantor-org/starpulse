// The `next` events of a GraphQL subscription answered as a graphql-sse event stream.

import { QUIET_MS } from "./retry";

/** A subscription's watch for silence: `signal` aborts with `stop`, or once QUIET_MS pass with no byte `heard`; `stop` ends the watch. */
export type Hush = { signal: AbortSignal; heard(): void; done(): void };

/**
 * The server pings every subscription at least every 15 s, so one that sends nothing for QUIET_MS is a connection gone
 * quiet without closing (a frozen server, an orphaned QUIC path): cutting it drops the page to retrying instead of
 * leaving it live on an old board. The wait starts at once, so it also covers a response that never starts; aborting
 * the fetch's signal errors its body, which ends the read.
 */
export function hush(stop: AbortSignal): Hush {
  const cut = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const done = () => clearTimeout(timer);
  const heard = () => {
    done();
    if (!stop.aborted) timer = setTimeout(() => cut.abort(new DOMException(`no byte for ${QUIET_MS} ms`, "TimeoutError")), QUIET_MS);
  };
  stop.addEventListener("abort", done, { once: true }); // a closed subscription whose fetch never settles keeps no timer
  heard();
  return { signal: AbortSignal.any([stop, cut.signal]), heard, done };
}

/** The `next` frames of one SSE body, each as its parsed data, until the stream ends; `heard` is told of every chunk. */
export async function* frames(body: ReadableStream<Uint8Array>, heard: () => void): AsyncGenerator<unknown> {
  const reader = body.getReader(), text = new TextDecoder();
  let rest = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      heard();
      rest += text.decode(value, { stream: true });
      for (let at = rest.indexOf("\n\n"); at >= 0; at = rest.indexOf("\n\n")) {
        const lines = rest.slice(0, at).split("\n");
        rest = rest.slice(at + 2);
        if (lines.some((l) => l === "event: next")) yield JSON.parse(lines.filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n"));
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
