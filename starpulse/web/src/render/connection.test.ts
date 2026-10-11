import { describe, expect, it } from "vitest";
import { UPDATING, linkHud } from "./connection";

describe("what the status dot and its note say of the connection", () => {
  it("is green with the stats line when live, and says the update waits for idle once a new build is loaded", () => {
    expect(linkHud("live", "18:00", false)).toEqual({ live: "on", note: "" });
    expect(linkHud("live", "18:00", true)).toEqual({ live: "on", note: UPDATING });
  });

  it("is amber and waiting, with the time of the last data, for an announced restart and for an unannounced drop", () => {
    expect(linkHud("restarting", "18:00", false)).toEqual({ live: "wait", note: "restarting · 18:00 MST" });
    expect(linkHud("retrying", "6:00 pm", false)).toEqual({ live: "wait", note: "retrying · 6:00 pm MST" });
  });

  it("is red once the connection is lost", () => {
    expect(linkHud("offline", "18:00", false)).toEqual({ live: "off", note: "offline · 18:00 MST" });
  });

  it("names no time when the page has drawn no data yet", () => {
    expect(linkHud("retrying", null, false)).toEqual({ live: "wait", note: "retrying" });
  });
});
