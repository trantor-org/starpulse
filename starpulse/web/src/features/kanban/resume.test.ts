import { describe, expect, it, vi } from "vitest";
import type { Roles } from "../../api";
import { postResume, resumable, resumedLink } from "./resume";

const ROLES: Roles = { review: "review", waiting: "waiting", attention: "needs_attention", working: "in_progress", startable: ["ready"] };
const SESSION = "https://claude.ai/code/session_01";

describe("resumable", () => {
  it("is the lanes a session parks from", () => {
    expect(["review", "waiting", "needs_attention"].map((lane) => resumable(lane, ROLES))).toEqual([true, true, true]);
    expect(["ready", "in_progress", "done"].map((lane) => resumable(lane, ROLES))).toEqual([false, false, false]);
  });

  it("is nothing for a board whose machine names no such lane", () => {
    expect(resumable("review", {})).toBe(false);
  });
});

describe("postResume", () => {
  it("POSTs the task and the trimmed reply to /api/resume and reads the new session", async () => {
    const fetcher = vi.fn<typeof fetch>(() => Promise.resolve(new Response(JSON.stringify({ task: "TASK-D1", url: SESSION, recorded: true }))));

    expect(await postResume("TASK-D1", "  fix the typo ", fetcher)).toEqual({ ok: true, url: SESSION });
    expect(fetcher).toHaveBeenCalledWith("/api/resume", { method: "POST", body: JSON.stringify({ task: "TASK-D1", text: "fix the typo" }) });
  });

  it("sends no text for a blank reply", async () => {
    const fetcher = vi.fn<typeof fetch>(() => Promise.resolve(new Response(JSON.stringify({ task: "TASK-D1", url: SESSION, recorded: true }))));

    await postResume("TASK-D1", "   ", fetcher);

    expect(fetcher).toHaveBeenCalledWith("/api/resume", { method: "POST", body: JSON.stringify({ task: "TASK-D1" }) });
  });

  it("reads a refusal's reason, and an unreachable server as one", async () => {
    const refused = vi.fn<typeof fetch>(() => Promise.resolve(new Response(JSON.stringify({ error: "TASK-D1 has a live session" }), { status: 502 })));
    const down = vi.fn<typeof fetch>(() => Promise.reject(new Error("offline")));

    expect(await postResume("TASK-D1", "", refused)).toEqual({ ok: false, reason: "TASK-D1 has a live session" });
    expect(await postResume("TASK-D1", "", down)).toEqual({ ok: false, reason: "the resume did not reach the server" });
  });
});

describe("resumedLink", () => {
  it("is the session the latest resume recorded, and null before any", () => {
    const comment = (text: string) => ({ created: "2026-11-03T10:00:00Z", text });

    expect(resumedLink([comment("hello"), comment(`Resumed in ${SESSION}`), comment(`Resumed in ${SESSION}2`)])).toBe(`${SESSION}2`);
    expect(resumedLink([comment("hello")])).toBeNull();
  });
});
