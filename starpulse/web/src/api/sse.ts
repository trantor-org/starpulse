// The `next` events of a GraphQL subscription answered as a graphql-sse event stream.

/** The `next` frames of one SSE body, each as its parsed data, until the stream ends. */
export async function* frames(body: ReadableStream<Uint8Array>): AsyncGenerator<unknown> {
  const reader = body.getReader(), text = new TextDecoder();
  let rest = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
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
