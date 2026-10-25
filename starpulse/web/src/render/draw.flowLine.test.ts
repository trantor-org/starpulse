import { describe, expect, it } from "vitest";
import { drawing } from "./draw";

/** A canvas that keeps the dash offset each flow line leaves behind. */
function recordingCanvas() {
  const ctx = { lineDashOffset: 0, setLineDash() {}, createLinearGradient: () => ({ addColorStop() {} }) };
  return ctx as unknown as CanvasRenderingContext2D;
}

const a = { x: 0, y: 0, color: "#4f9cff" };
const b = { x: 100, y: 40, color: "#ff8a4f" };

describe("flowLine", () => {
  it("holds its dashes in place as the ambient clock runs", () => {
    const offsets = [0, 1.3, 7.9].map((clock) => {
      const cx = recordingCanvas();
      drawing({ cx, K: 1.4, ZS: 1, clock, scale: 100, hover: null }).flowLine(a, b, 0.5, 0.2);
      return cx.lineDashOffset;
    });
    expect(offsets).toEqual([0, 0, 0]);
  });
});
