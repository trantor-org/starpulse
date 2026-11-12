import { describe, expect, it } from "vitest";
import type { Sky } from "./sky";
import { skillOf } from "./skills";

const link = (machine: string, skill?: string) => ({ state: "s", machine, exits: {}, parent: "board", when: "", ...(skill === undefined ? {} : { skill }) });
const flows = (...links: ReturnType<typeof link>[]) => ({ board: { machine: { submachines: links } } }) as unknown as Sky["flows"];

describe("the skill a machine runs", () => {
  it("is the skill of the submachine link that opens it, wherever the link hangs", () => {
    const f = { ...flows(link("build", "tdd")), qa: { machine: { submachines: [link("cr-triage", "cr-triage")] } } } as unknown as Sky["flows"];

    expect(skillOf(f, "build")).toBe("tdd");
    expect(skillOf(f, "cr-triage")).toBe("cr-triage");
  });

  it("is undefined for a machine no link opens or whose link names no skill", () => {
    expect(skillOf(flows(link("qa", "")), "qa")).toBeUndefined();
    expect(skillOf(flows(link("qa")), "qa")).toBeUndefined();
    expect(skillOf(flows(link("qa", "qa")), "deliver")).toBeUndefined();
  });
});
