import { describe, expect, it, vi } from "vitest";
import { openHealth, type Health } from "./health";

const HEALTH: Health = { components: [{ name: "board", ready: true, detail: "ok" }], build: "b-1", restarting: false, at: 5 };
const sse = (...nexts: unknown[]) =>
  new Response(new ReadableStream({ start(c) { for (const data of nexts) c.enqueue(new TextEncoder().encode(`event: next\ndata: ${JSON.stringify({ data })}\n\n`)); c.close(); } }));
const watch = (post: () => Promise<Response>) => {
  const seen: Health[] = [];
  const ended = new Promise<void>((end) => openHealth({ health: (h) => void seen.push(h), end }, post));
  return { seen, ended };
};

describe("the health subscription", () => {
  it("is one POST /graphql of the health subscription, handing over each health the server sends", async () => {
    const post = vi.fn(async () => sse({ health: HEALTH }, { health: { ...HEALTH, restarting: true } }));
    const { seen, ended } = watch(post);

    await ended;

    expect(post).toHaveBeenCalledWith("/graphql", expect.objectContaining({ method: "POST", body: expect.stringContaining("subscription { health {") }));
    expect(seen.map((h) => h.restarting)).toEqual([false, true]);
  });

  it("ends when the server refuses it, or cannot be reached", async () => {
    for (const post of [async () => new Response("no", { status: 410 }), async () => Promise.reject(new Error("offline"))]) {
      const { seen, ended } = watch(post);
      await ended;
      expect(seen).toEqual([]);
    }
  });

  it("says nothing more once closed", async () => {
    const seen: Health[] = [];
    const end = vi.fn();
    const subscription = openHealth({ health: (h) => void seen.push(h), end }, async () => sse({ health: HEALTH }));

    subscription.close();
    await new Promise((done) => setTimeout(done, 0));

    expect([seen, end.mock.calls]).toEqual([[], []]);
  });
});
