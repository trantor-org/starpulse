import { describe, expect, it, vi } from "vitest";
import type { KanbanTask } from "./kanban";
import { MoveStore, codeParts, place, postMove, targets, type Post, type Reply } from "./move";

const OK = { allowed: true, reason: "", skill: "" };
const GUARD = { allowed: false, reason: "a checked criterion opening `Operator approved the render:` is not recorded", skill: "designing-ui" };
const task = (id: string, lane: string, moves: KanbanTask["moves"] = {}): KanbanTask => ({
  id, title: id, lane, milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, moves, entered: 0,
});
/** A writer the test settles by hand, so the card can be read while the request is in flight. */
const writer = () => {
  let settle!: (r: Reply) => void;
  const post = vi.fn<Post>(() => new Promise<Reply>((resolve) => (settle = resolve)));
  return { post, settle: (r: Reply) => settle(r) };
};

describe("a drop", () => {
  it("on a guarded column is refused on the card with the guard's reason and skill, and sends no request", async () => {
    const { post } = writer();
    const store = new MoveStore(post, () => 900);

    await store.drop(task("PROJ-1", "in_progress", { review: GUARD }), "review");

    expect(post).not.toHaveBeenCalled();
    expect(store.get().refused["PROJ-1"]).toEqual({ from: "in_progress", to: "review", reason: GUARD.reason, skill: "designing-ui" });
    expect(store.get().pending).toEqual({});
  });

  it("on a column the machine does not offer is refused without a request", async () => {
    const { post } = writer();
    const store = new MoveStore(post, () => 900);

    await store.drop(task("PROJ-1", "ready", { in_progress: OK }), "done");

    expect(post).not.toHaveBeenCalled();
    expect(store.get().refused["PROJ-1"]).toMatchObject({ from: "ready", to: "done", skill: "" });
  });

  it("on its own column does nothing", async () => {
    const { post } = writer();
    const store = new MoveStore(post, () => 900);

    await store.drop(task("PROJ-1", "ready", { in_progress: OK }), "ready");

    expect(post).not.toHaveBeenCalled();
    expect(store.get()).toEqual({ pending: {}, refused: {} });
  });

  it("on an allowed column lands at once, marked saving, while the writer is still asked", () => {
    const { post } = writer();
    const store = new MoveStore(post, () => 900);
    const t = task("PROJ-1", "ready", { in_progress: OK });

    void store.drop(t, "in_progress");

    expect(post).toHaveBeenCalledWith("PROJ-1", "in_progress");
    expect(store.get().pending["PROJ-1"]).toEqual({ from: "ready", to: "in_progress", saving: true, at: 900 });
    expect(place([t], store.get())[0]).toMatchObject({ lane: "in_progress", live: { machine: "board", state: "in_progress", at: 900 } });
  });

  it("keeps the card in its new column, no longer saving, once the writer confirms and until the stream reports it", async () => {
    const { post, settle } = writer();
    const store = new MoveStore(post, () => 900);
    const t = task("PROJ-1", "ready", { in_progress: OK });

    const dropped = store.drop(t, "in_progress");
    settle({ ok: true });
    await dropped;

    expect(store.get().pending["PROJ-1"]).toEqual({ from: "ready", to: "in_progress", saving: false, at: 900 });
    store.sync([t]);
    expect(store.get().pending["PROJ-1"]).toBeDefined();
    store.sync([task("PROJ-1", "in_progress")]);
    expect(store.get().pending).toEqual({});
  });

  it("returns the card with the writer's reason and skill when the writer refuses late", async () => {
    const { post, settle } = writer();
    const store = new MoveStore(post, () => 900);
    const t = task("PROJ-1", "in_progress", { review: OK });

    const dropped = store.drop(t, "review");
    expect(place([t], store.get())[0].lane).toBe("review");
    settle({ ok: false, reason: "the delivery changed", skill: "designing-ui" });
    await dropped;

    expect(place([t], store.get())[0].lane).toBe("in_progress");
    expect(store.get().pending).toEqual({});
    expect(store.get().refused["PROJ-1"]).toEqual({ from: "in_progress", to: "review", reason: "the delivery changed", skill: "designing-ui" });
  });

  it("ignores a second drop of a card whose first is still unconfirmed", () => {
    const { post } = writer();
    const store = new MoveStore(post, () => 900);
    const t = task("PROJ-1", "ready", { in_progress: OK, waiting: OK });

    void store.drop(t, "in_progress");
    void store.drop(t, "waiting");

    expect(post).toHaveBeenCalledTimes(1);
  });
});

describe("a refusal", () => {
  it("clears on dismiss, on the next drop of that card, and when the card has left the lane it was refused in", async () => {
    const { post } = writer();
    const store = new MoveStore(post, () => 900);
    const t = task("PROJ-1", "in_progress", { review: GUARD, ready: OK });
    await store.drop(t, "review");

    store.dismiss("PROJ-1");
    expect(store.get().refused).toEqual({});

    await store.drop(t, "review");
    void store.drop(t, "ready");
    expect(store.get().refused).toEqual({});

    await store.drop(t, "review");
    store.sync([task("PROJ-1", "review")]);
    expect(store.get().refused).toEqual({});
  });
});

describe("the columns a drag offers", () => {
  const t = task("PROJ-1", "in_progress", { ready: OK, review: GUARD });
  const columns = ["ready", "waiting", "in_progress", "review"];

  it("mark the card's own column, each allowed column, each guarded one with its verdict, and every other as no transition", () => {
    expect(targets(t, columns)).toEqual({
      ready: { kind: "ok" },
      waiting: { kind: "no" },
      in_progress: { kind: "here" },
      review: { kind: "guard", reason: GUARD.reason, skill: "designing-ui" },
    });
  });
});

describe("a change to the board while a move is pending", () => {
  it("drops a pending move when the stream moves the card somewhere else", async () => {
    const { post, settle } = writer();
    const store = new MoveStore(post, () => 900);
    const dropped = store.drop(task("PROJ-1", "ready", { in_progress: OK }), "in_progress");

    store.sync([task("PROJ-1", "review")]);
    settle({ ok: true });
    await dropped;

    expect(store.get().pending).toEqual({});
  });

  it("notifies subscribers on every change", () => {
    const { post } = writer();
    const store = new MoveStore(post, () => 900);
    const seen = vi.fn();
    store.subscribe(seen);

    void store.drop(task("PROJ-1", "ready", { in_progress: OK }), "in_progress");

    expect(seen).toHaveBeenCalled();
  });
});

describe("posting a move", () => {
  const reply = (status: number, body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status }));

  it("sends the task and column as JSON to /api/move", async () => {
    const fetcher = reply(200, { task: "PROJ-1", to: "review" });

    expect(await postMove("PROJ-1", "review", fetcher)).toEqual({ ok: true });
    expect(fetcher).toHaveBeenCalledWith("/api/move", { method: "POST", body: JSON.stringify({ task: "PROJ-1", to: "review" }) });
  });

  it("carries the writer's refusal and the skill it names", async () => {
    expect(await postMove("PROJ-1", "review", reply(409, { error: "no render approval", skill: "designing-ui" }))).toEqual({
      ok: false, reason: "no render approval", skill: "designing-ui",
    });
  });

  it("reports a server that cannot be reached, or answers with no JSON, as a refusal", async () => {
    const down = vi.fn(async () => { throw new TypeError("fetch failed"); });
    const html = vi.fn(async () => new Response("<html>", { status: 502 }));

    expect(await postMove("PROJ-1", "review", down)).toMatchObject({ ok: false, skill: "" });
    expect(await postMove("PROJ-1", "review", html)).toMatchObject({ ok: false, reason: expect.stringContaining("502"), skill: "" });
  });
});

describe("a reason's code spans", () => {
  it("split at backticks so the page can set the quoted text as code", () => {
    expect(codeParts("no `Operator approved the render:` recorded")).toEqual([
      { code: false, text: "no " }, { code: true, text: "Operator approved the render:" }, { code: false, text: " recorded" },
    ]);
  });

  it("leave text with no backticks, or an unclosed one, as plain text", () => {
    expect(codeParts("plain")).toEqual([{ code: false, text: "plain" }]);
    expect(codeParts("an `open")).toEqual([{ code: false, text: "an `open" }]);
  });
});
