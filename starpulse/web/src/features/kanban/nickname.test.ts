import { describe, expect, it } from "vitest";
import { sessionNickname } from "./nickname";

const url = (id: string) => `https://claude.ai/code/session_${id}`;

describe("sessionNickname", () => {
  it("names a session URL with an adjective and an animal", () => {
    expect(sessionNickname(url("01AbCdEfGh"))).toMatch(/^[a-z]+-[a-z]+$/);
  });

  it("gives the same session the same name every time", () => {
    expect(sessionNickname(url("01AbCdEfGh"))).toBe(sessionNickname(url("01AbCdEfGh")));
  });

  it("tells sessions apart that share their first characters", () => {
    const names = new Set(Array.from({ length: 40 }, (_, i) => sessionNickname(url(`01AbCdEfGh${i}`))));
    expect(names.size).toBeGreaterThan(35);
  });

  it("gives sessions that differ only in their last character different animals", () => {
    const animals = new Set(Array.from({ length: 10 }, (_, i) => sessionNickname(url(`demo15${i}`))?.split("-")[1]));
    expect(animals.size).toBeGreaterThan(6);
  });

  it("names nothing that is not a session URL", () => {
    expect(sessionNickname("@agent-deep-high")).toBeNull();
    expect(sessionNickname("local")).toBeNull();
    expect(sessionNickname("")).toBeNull();
  });
});
