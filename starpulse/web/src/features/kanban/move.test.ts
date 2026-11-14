import { describe, expect, it, vi } from "vitest";
import type { KanbanTask } from "./kanbanModel";
import { MoveStore, codeParts, place, postMove, targets, type Post, type Reply } from "./move";

const OK = { allowed: true, reason: "", skill: "" };
const GUARD = { allowed: false, reason: "a checked criterion opening `Operator approved the render:` is not recorded", skill: "designing-ui" };
const task = (id: string, lane: string, moves: KanbanTask["moves"] = {}): KanbanTask => ({
  id, title: id, lane, milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, moves, entered: 0, created: null, workableSince: null, machines: [],
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
    expect(store.get()).toEqual({ pending: {}, refused: {}, asking: null });
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
    expect(fetcher).toHaveBeenCalledWith("/api/move", { method: "POST", body: JSON.stringify({ task: "PROJ-1", to: "review", actor: "operator" }) });
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

describe("a move the board machine leaves to the agent alone", () => {
  const AGENT_ONLY = { ...OK, writers: ["agent"] };
  const t = task("PROJ-1", "needs_attention", { review: AGENT_ONLY, ready: { ...OK, writers: ["operator"] } });

  it("is no drop for the operator, with the writers it names, while a move the operator writes stays allowed", () => {
    const columns = ["needs_attention", "review", "ready"];
    expect(targets(t, columns)).toEqual({
      needs_attention: { kind: "here" },
      review: { kind: "guard", reason: "only the agent may make this move, not the operator", skill: "" },
      ready: { kind: "ok" },
    });
  });

  it("is refused on the card with no request", async () => {
    const { post } = writer();
    const store = new MoveStore(post, () => 900);
    await store.drop(t, "review");

    expect(post).not.toHaveBeenCalled();
    expect(store.get().refused["PROJ-1"].reason).toBe("only the agent may make this move, not the operator");
  });
});

describe("a move a guard refuses the agent but exempts the operator", () => {
  const ASKS = { allowed: false, reason: "only the operator answers the question", skill: "", actors: { operator: { allowed: true, reason: "", skill: "" } } };
  const PROFILE = { allowed: false, reason: "a Ready task needs an agent profile", skill: "", actors: { operator: { allowed: false, reason: "a Ready task needs an agent profile", skill: "" } } };
  const columns = ["needs_attention", "ready", "done"];

  it("is a drop for the operator on the verdict the guard names for the operator", () => {
    const t = task("PROJ-1", "needs_attention", { ready: ASKS });
    expect(targets(t, columns).ready).toEqual({ kind: "ok" });
  });

  it("is still refused when another rule refuses the operator too", () => {
    const t = task("PROJ-1", "needs_attention", { ready: PROFILE });
    expect(targets(t, columns).ready).toMatchObject({ kind: "guard", reason: "a Ready task needs an agent profile" });
  });

  it("stays a guard refusal for a move that names no verdict for the operator", () => {
    const t = task("PROJ-1", "needs_attention", { ready: { allowed: false, reason: "asks", skill: "" } });
    expect(targets(t, columns).ready).toMatchObject({ kind: "guard", reason: "asks" });
  });
});

describe("a drop on a column whose rules the move breaks, for the operator", () => {
  const WARNINGS = [{ reason: "Review needs every Acceptance Criterion checked", skill: "" }, { reason: "a Review task needs a pull request", skill: "deliver" }];
  const WARNS = { allowed: false, reason: WARNINGS[0].reason, skill: "", actors: { operator: { allowed: true, reason: "", skill: "", warnings: WARNINGS } } };
  const t = task("PROJ-1", "in_progress", { review: WARNS });

  it("is a drop target that asks first, with no request and the card left where it is", async () => {
    const { post } = writer();
    const store = new MoveStore(post, () => 900);
    await store.drop(t, "review");

    expect(targets(t, ["in_progress", "review"]).review).toEqual({ kind: "ok" });
    expect(post).not.toHaveBeenCalled();
    expect(store.get().pending).toEqual({});
    expect(store.get().asking).toMatchObject({ task: { id: "PROJ-1" }, to: "review", warnings: WARNINGS, busy: false, refused: null });
  });

  it("writes nothing when cancelled", async () => {
    const { post } = writer();
    const store = new MoveStore(post, () => 900);
    await store.drop(t, "review");
    store.cancel();

    expect(post).not.toHaveBeenCalled();
    expect(store.get()).toEqual({ pending: {}, refused: {}, asking: null });
  });

  it("writes the move when confirmed: the card waits in the target lane while the dialog is busy, then both settle", async () => {
    const { post, settle } = writer();
    const store = new MoveStore(post, () => 900);
    await store.drop(t, "review");
    const done = store.confirm();

    expect(post).toHaveBeenCalledWith("PROJ-1", "review");
    expect(store.get().pending["PROJ-1"]).toMatchObject({ to: "review", saving: true });
    expect(store.get().asking?.busy).toBe(true);
    store.cancel();
    expect(store.get().asking).not.toBeNull();
    settle({ ok: true });
    await done;

    expect(store.get().asking).toBeNull();
    expect(store.get().pending["PROJ-1"]).toMatchObject({ saving: false });
  });

  it("keeps the dialog on a refused confirm, the card home and no refusal on the card", async () => {
    const { post, settle } = writer();
    const store = new MoveStore(post, () => 900);
    await store.drop(t, "review");
    const done = store.confirm();
    settle({ ok: false, reason: "changed", skill: "" });
    await done;

    expect(store.get().pending).toEqual({});
    expect(store.get().refused).toEqual({});
    expect(store.get().asking).toMatchObject({ busy: false, refused: "changed" });
    await store.confirm();
    expect(post).toHaveBeenCalledTimes(1);
    store.cancel();
    expect(store.get().asking).toBeNull();
  });

  it("stays open when an unwarned drop settles while it waits", async () => {
    const { post, settle } = writer();
    const store = new MoveStore(post, () => 900);
    const other = task("PROJ-2", "in_progress", { review: OK });
    const dropped = store.drop(other, "review");
    await store.drop(t, "review");
    settle({ ok: true });
    await dropped;

    expect(store.get().asking).toMatchObject({ task: { id: "PROJ-1" }, busy: false });
    expect(store.get().pending["PROJ-2"]).toMatchObject({ saving: false });
  });

  it("closes when the streamed board moves the card out of its lane, unless the write is running", async () => {
    const { post } = writer();
    const store = new MoveStore(post, () => 900);
    await store.drop(t, "review");
    store.sync([{ ...t, lane: "review" }]);

    expect(store.get().asking).toBeNull();
  });
});

describe("a drop judged by the board's standing guards", () => {
  const WARNINGS = [{ reason: "a Review task needs a pull request", skill: "deliver" }];
  const WARNS = { allowed: false, reason: WARNINGS[0].reason, skill: "", actors: { operator: { allowed: true, reason: "", skill: "", warnings: WARNINGS } } };
  const unjudged = task("PROJ-1", "in_progress", { review: OK, ready: OK });

  it("asks with the warnings the guarded read names, though the streamed card carried none", async () => {
    const { post } = writer();
    const standing = vi.fn(async () => ({ review: WARNS }));
    const store = new MoveStore(post, () => 900, standing);
    await store.drop(unjudged, "review");

    expect(standing).toHaveBeenCalledWith("PROJ-1");
    expect(post).not.toHaveBeenCalled();
    expect(store.get().asking).toMatchObject({ to: "review", warnings: WARNINGS });
  });

  it("refuses on the card when the guarded read says a guard refuses the operator", async () => {
    const { post } = writer();
    const store = new MoveStore(post, () => 900, async () => ({ review: GUARD }));
    await store.drop(unjudged, "review");

    expect(post).not.toHaveBeenCalled();
    expect(store.get().refused["PROJ-1"].reason).toBe(GUARD.reason);
  });

  it("falls back to the card's own verdict when the guarded read fails", async () => {
    const { post } = writer();
    const store = new MoveStore(post, () => 900, async () => null);
    void store.drop(unjudged, "ready");
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith("PROJ-1", "ready"));
  });

  it("reads the guarded moves once for a drop that lands on an unwarned column", async () => {
    const { post } = writer();
    const standing = vi.fn(async () => ({ ready: OK }));
    const store = new MoveStore(post, () => 900, standing);
    void store.drop(unjudged, "ready");
    await vi.waitFor(() => expect(post).toHaveBeenCalled());

    expect(standing).toHaveBeenCalledTimes(1);
  });
});
