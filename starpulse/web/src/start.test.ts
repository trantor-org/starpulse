import { describe, expect, it, vi } from "vitest";
import type { KanbanTask } from "./kanban";
import { MoveStore, type Post, type Reply } from "./move";
import {
  StartStore, canDrag, choose, defaultPick, dropAsks, fetchHarnesses, placeClaims, postStart, profileOf, runsOn, startable,
  type Harnesses, type PostStart, type StartReply,
} from "./start";

const OK = { allowed: true, reason: "", skill: "" };
const GUARD = { allowed: false, reason: "TASK-D3 is not Done", skill: "" };
const task = (id: string, lane: string, assignee = "", moves: KanbanTask["moves"] = { in_progress: OK }): KanbanTask => ({
  id, title: id, lane, milestone: "", labels: [], assignee, dependencies: [], openDeps: 0, prs: [], description: "", live: null, moves,
});
const HARNESSES: Harnesses = {
  tiers: ["fast", "standard", "deep"],
  harnesses: [
    {
      name: "claude", label: "Claude Code", sessions: true, reason: "",
      tiers: { fast: { model: "haiku", efforts: [] }, standard: { model: "sonnet", efforts: ["medium", "high"] }, deep: { model: "opus", efforts: ["medium", "high"] } },
    },
    { name: "codex", label: "Codex", sessions: false, reason: "Remote Control is Claude's", tiers: { standard: { model: "gpt-5", efforts: ["medium", "high"] } } },
  ],
};
const SESSION = "https://claude.ai/code/session_01";

/** A session-start the test settles by hand, so the card can be read while the start is in flight. */
const service = () => {
  let settle!: (r: StartReply) => void;
  const post = vi.fn<PostStart>(() => new Promise<StartReply>((resolve) => (settle = resolve)));
  return { post, settle: (r: StartReply) => settle(r) };
};
const stores = () => {
  const writer = vi.fn<Post>(() => Promise.resolve<Reply>({ ok: true }));
  const moves = new MoveStore(writer, () => 900);
  const { post, settle } = service();
  return { writer, moves, post, settle, starts: new StartStore(post, moves, HARNESSES) };
};
const flush = () => new Promise((r) => setTimeout(r));

describe("the start question", () => {
  it.each(["ready", "waiting", "needs_attention"])("is asked when a %s card is dropped on In progress", (lane) => {
    expect(dropAsks(task("TASK-D1", lane), "in_progress")).toBe(true);
  });

  it("is not asked for another column, for Review's send-back, or for a move a guard refuses", () => {
    expect(dropAsks(task("TASK-D1", "ready", "", { waiting: OK, in_progress: OK }), "waiting")).toBe(false);
    expect(dropAsks(task("TASK-D1", "review"), "in_progress")).toBe(false);
    expect(dropAsks(task("TASK-D1", "waiting", "", { in_progress: GUARD }), "in_progress")).toBe(false);
    expect(startable(task("TASK-D1", "waiting", "", { in_progress: GUARD }))).toBe(false);
  });

  it.each(["drop", "modal", "play"] as const)("opens from a %s on the task with its pick", (via) => {
    const { starts } = stores();

    starts.ask(task("TASK-D1", "ready", "@agent-deep-medium"), via);

    expect(starts.get().asking).toMatchObject({ task: { id: "TASK-D1" }, via, pick: { harness: "claude", tier: "deep", effort: "medium" } });
  });

  it("key 1 starts a session on the picked profile and key 2 moves the task without one", async () => {
    const { starts, post, moves, writer } = stores();
    starts.ask(task("TASK-D1", "ready"), "play");
    starts.pick({ tier: "deep" });

    expect(starts.key("1")).toBe(true);
    expect(post).toHaveBeenCalledWith("TASK-D1", "@agent-deep-high");
    expect(starts.get().asking).toBeNull();

    starts.ask(task("TASK-D2", "waiting"), "drop");
    expect(starts.key("2")).toBe(true);
    await flush();
    expect(writer).toHaveBeenCalledWith("TASK-D2", "in_progress");
    expect(moves.get().pending["TASK-D2"]).toMatchObject({ from: "waiting", to: "in_progress" });
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("Esc returns the card and starts nothing", () => {
    const { starts, post, writer } = stores();
    starts.ask(task("TASK-D1", "ready"), "drop");

    expect(starts.key("Escape")).toBe(true);
    expect(starts.get().asking).toBeNull();
    expect(post).not.toHaveBeenCalled();
    expect(writer).not.toHaveBeenCalled();
    expect(starts.key("1")).toBe(false); // nothing is asked now
  });

  it("starts no session when no harness can run one, and still works it manually", async () => {
    const writer = vi.fn<Post>(() => Promise.resolve<Reply>({ ok: true }));
    const { post } = service();
    const starts = new StartStore(post, new MoveStore(writer, () => 900));
    starts.ask(task("TASK-D1", "ready"), "play");

    expect(starts.canStart()).toBe(false);
    expect(starts.key("1")).toBe(false);
    expect(post).not.toHaveBeenCalled();
    expect(starts.key("2")).toBe(true);
    await flush();
    expect(writer).toHaveBeenCalledWith("TASK-D1", "in_progress");
  });

  it("offers the harnesses the server named once they load", () => {
    const { post } = service();
    const starts = new StartStore(post, new MoveStore(vi.fn<Post>(), () => 900));

    starts.load(HARNESSES);
    starts.ask(task("TASK-D1", "ready"), "play");

    expect([starts.get().harnesses, starts.canStart()]).toEqual([HARNESSES, true]);
  });

  it("is not asked for a card already waiting for its claim", () => {
    const { starts } = stores();
    starts.ask(task("TASK-D1", "ready"), "play");
    starts.key("1");

    starts.ask(task("TASK-D1", "ready"), "play");

    expect(starts.get().asking).toBeNull();
  });
});

describe("the pick", () => {
  it("defaults to the task's assignee, or @agent-standard-high", () => {
    expect(defaultPick("@agent-deep-medium", HARNESSES)).toEqual({ harness: "claude", tier: "deep", effort: "medium" });
    expect(defaultPick("", HARNESSES)).toEqual({ harness: "claude", tier: "standard", effort: "high" });
    expect(defaultPick("@someone", HARNESSES)).toEqual({ harness: "claude", tier: "standard", effort: "high" });
  });

  it("drops the effort for a tier that takes none and restores one for a tier that does", () => {
    const fast = choose({ harness: "claude", tier: "standard", effort: "medium" }, HARNESSES, { tier: "fast" });
    expect(fast).toEqual({ harness: "claude", tier: "fast", effort: "" });
    expect(profileOf(fast)).toBe("@agent-fast");
    expect(choose(fast, HARNESSES, { tier: "deep" })).toEqual({ harness: "claude", tier: "deep", effort: "high" });
  });

  it("names the model, effort and harness it runs on", () => {
    expect(runsOn({ harness: "claude", tier: "standard", effort: "medium" }, HARNESSES)).toBe("runs sonnet at medium effort on Claude Code");
    expect(runsOn({ harness: "claude", tier: "fast", effort: "" }, HARNESSES)).toBe("runs haiku on Claude Code");
  });
});

describe("a started card", () => {
  it("moves to In progress at once, marked starting, then waiting for its claim with the session link", async () => {
    const { starts, settle } = stores();
    const t = task("TASK-D1", "ready");
    starts.ask(t, "play");
    starts.key("1");

    expect(starts.get().claiming["TASK-D1"]).toEqual({ from: "ready", phase: "starting", url: "", at: null });
    expect(placeClaims([t], starts.get())[0].lane).toBe("in_progress");
    expect(canDrag("TASK-D1", starts.get())).toBe(false);

    settle({ ok: true, url: SESSION, at: 1000 });
    await flush();

    expect(starts.get().claiming["TASK-D1"]).toEqual({ from: "ready", phase: "waiting", url: SESSION, at: 1000 });
  });

  it("returns to its column with the reason when the start fails", async () => {
    const { starts, settle } = stores();
    const t = task("TASK-D1", "waiting");
    starts.ask(t, "play");
    starts.key("1");

    settle({ ok: false, reason: "tmux could not start session task-1" });
    await flush();

    expect(starts.get().claiming).toEqual({});
    expect(starts.get().failed["TASK-D1"]).toEqual({ from: "waiting", reason: "tmux could not start session task-1", url: "", refused: false });
    expect(placeClaims([t], starts.get())[0].lane).toBe("waiting");
    expect(canDrag("TASK-D1", starts.get())).toBe(true);
  });

  it("returns to its column with the writer's reason and keeps the session link when the claim is refused", async () => {
    const { starts, settle } = stores();
    const t = task("TASK-D1", "waiting");
    starts.ask(t, "play");
    starts.key("1");
    settle({ ok: true, url: SESSION, at: 1000 });
    await flush();

    starts.sync([t], { "TASK-D1": { reason: "TASK-D3 is not Done", at: 999 } }); // an older refusal, before this start
    expect(starts.get().claiming["TASK-D1"]?.phase).toBe("waiting");

    starts.sync([t], { "TASK-D1": { reason: "TASK-D3 is not Done", at: 1001 } });

    expect(starts.get().claiming).toEqual({});
    expect(starts.get().failed["TASK-D1"]).toEqual({ from: "waiting", reason: "TASK-D3 is not Done", url: SESSION, refused: true });
    expect(placeClaims([t], starts.get())[0].lane).toBe("waiting");

    starts.dismiss("TASK-D1");
    expect(starts.get().failed).toEqual({});
  });

  it("applies a refusal the stream reported before the start answered", async () => {
    const { starts, settle } = stores();
    const t = task("TASK-D1", "ready");
    starts.ask(t, "play");
    starts.key("1");
    starts.sync([t], { "TASK-D1": { reason: "refused", at: 1001 } });

    settle({ ok: true, url: SESSION, at: 1000 });
    await flush();

    expect(starts.get().failed["TASK-D1"]).toMatchObject({ reason: "refused", refused: true, url: SESSION });
  });

  it("clears its mark once the projection reports the agent's claim", async () => {
    const { starts, settle } = stores();
    starts.ask(task("TASK-D1", "ready"), "play");
    starts.key("1");
    settle({ ok: true, url: SESSION, at: 1000 });
    await flush();

    starts.sync([task("TASK-D1", "in_progress")], {});

    expect(starts.get().claiming).toEqual({});
    expect(starts.get().failed).toEqual({});
  });
});

describe("the requests", () => {
  it("POSTs the task and its assignee to /api/start and reads the session and when the start began", async () => {
    const fetcher = vi.fn<typeof fetch>(() => Promise.resolve(new Response(JSON.stringify({ task: "TASK-D1", url: SESSION, at: 1000 }))));

    expect(await postStart("TASK-D1", "@agent-deep-high", fetcher)).toEqual({ ok: true, url: SESSION, at: 1000 });
    expect(fetcher).toHaveBeenCalledWith("/api/start", { method: "POST", body: JSON.stringify({ task: "TASK-D1", assignee: "@agent-deep-high" }) });
  });

  it("reads a refused or failed start's reason, and an unreachable server as one", async () => {
    const refused = vi.fn<typeof fetch>(() => Promise.resolve(new Response(JSON.stringify({ error: "tmux failed" }), { status: 502 })));
    const down = vi.fn<typeof fetch>(() => Promise.reject(new Error("offline")));

    expect(await postStart("TASK-D1", "@a", refused)).toEqual({ ok: false, reason: "tmux failed" });
    expect(await postStart("TASK-D1", "@a", down)).toEqual({ ok: false, reason: "the start did not reach the server" });
  });

  it("reads the harnesses, and none when the server cannot say", async () => {
    const served = vi.fn<typeof fetch>(() => Promise.resolve(new Response(JSON.stringify(HARNESSES))));
    const down = vi.fn<typeof fetch>(() => Promise.reject(new Error("offline")));

    expect(await fetchHarnesses(served)).toEqual(HARNESSES);
    expect(await fetchHarnesses(down)).toEqual({ tiers: [], harnesses: [] });
  });
});
