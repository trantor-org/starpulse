import { describe, expect, it, vi } from "vitest";
import { createContract } from "./contract";

const REPORT = { ok: false, checks: [{ check: "repo:child", status: "fail" as const, reason: "child is not a submodule" }] };
const reply = (body: unknown, ok = true) => Promise.resolve({ ok, json: () => Promise.resolve(body) });
const settle = () => new Promise((r) => setTimeout(r, 0));

function rig(fetch: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }>) {
  let clock = 1000;
  const onChange = vi.fn(), f = vi.fn(fetch);
  return { contract: createContract({ onChange, fetch: f, now: () => clock, ttl: 60 }), onChange, f, tick: (s: number) => (clock += s) };
}

describe("the contract report", () => {
  it("is none until /api/doctor answers, is read once, tells the page, then holds the report", async () => {
    const { contract, onChange, f } = rig(() => reply(REPORT));

    expect(contract.report()).toBeNull();
    expect(contract.report()).toBeNull();
    await settle();

    expect(f).toHaveBeenCalledTimes(1);
    expect(f).toHaveBeenCalledWith("/api/doctor");
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(contract.report()).toEqual(REPORT);
  });

  it("keeps the report while a stale one is read again, and not before it is stale", async () => {
    const { contract, f, tick } = rig(() => reply(REPORT));
    contract.report();
    await settle();

    tick(59);
    contract.report();
    expect(f).toHaveBeenCalledTimes(1);

    tick(1);
    expect(contract.report()).toEqual(REPORT);
    expect(f).toHaveBeenCalledTimes(2);
  });

  it("keeps the last report through a read that fails, and shows none if none ever landed", async () => {
    let ok = true;
    const { contract, tick } = rig(() => (ok ? reply(REPORT) : reply({}, false)));
    contract.report();
    await settle();
    ok = false;
    tick(60);
    contract.report();
    await settle();

    expect(contract.report()).toEqual(REPORT);

    const none = rig(() => reply({}, false));
    none.contract.report();
    await settle();
    expect(none.contract.report()).toBeNull();
  });
});
