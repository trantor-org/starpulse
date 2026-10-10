import { describe, expect, it } from "vitest";
import { clockHm, fmtAt, stamp } from "./clock";

// 2026-10-02 01:00 UTC is 18:00 on Oct 1 in Arizona (UTC-7, no daylight saving time)
const SIX_PM = 1790902800;
const MIDNIGHT = 1790924400; // 2026-10-02 07:00 UTC = 00:00 Oct 2 in Arizona
const NOON = 1790967600; // 2026-10-02 19:00 UTC = 12:00 Oct 2 in Arizona
const EARLY = SIX_PM - 12 * 3600 + 5 * 60 + 9; // 06:05:09 Oct 1 in Arizona

describe("a time as the clock setting writes it", () => {
  it("writes 24-hour time with a padded hour", () => {
    expect(clockHm(SIX_PM, "24")).toBe("18:00");
    expect(clockHm(EARLY, "24")).toBe("06:05");
    expect(clockHm(MIDNIGHT, "24")).toBe("00:00");
  });

  it("writes 12-hour time with am or pm and no padded hour", () => {
    expect(clockHm(SIX_PM, "12")).toBe("6:00 pm");
    expect(clockHm(EARLY, "12")).toBe("6:05 am");
    expect(clockHm(MIDNIGHT, "12")).toBe("12:00 am");
    expect(clockHm(NOON, "12")).toBe("12:00 pm");
  });

  it("puts the date before the time in a stamp and a trace moment", () => {
    expect(stamp(SIX_PM, "24")).toBe("Oct 1, 2026, 18:00");
    expect(stamp(SIX_PM, "12")).toBe("Oct 1, 2026, 6:00 pm");
    expect(fmtAt(SIX_PM, "24")).toBe("Oct 1, 18:00");
    expect(fmtAt(SIX_PM, "12")).toBe("Oct 1, 6:00 pm");
    expect(fmtAt(SIX_PM)).toBe("Oct 1, 18:00");
  });

  it("rolls the date over in Arizona time, not UTC", () => {
    // 2027-01-01 06:59 UTC is 23:59 Dec 31 2026 in Arizona; one minute later it is Jan 1 2027
    const lastMinute = Date.UTC(2027, 0, 1, 6, 59) / 1000;
    expect(stamp(lastMinute, "24")).toBe("Dec 31, 2026, 23:59");
    expect(stamp(lastMinute + 60, "24")).toBe("Jan 1, 2027, 00:00");
    // 2028-03-01 06:59 UTC falls on the leap day in Arizona
    expect(fmtAt(Date.UTC(2028, 2, 1, 6, 59) / 1000, "12")).toBe("Feb 29, 11:59 pm");
  });
});
