import { describe, expect, it } from "vitest";
import { fitBox, fitLevel, refitView, toScreen, toWorld, wheelFactor, zoomAbout, type View } from "./zoom";

describe("fitBox", () => {
  it("centres the content box in the canvas at the largest scale that fits it", () => {
    const view = fitBox({ x0: 100, y0: 50, x1: 500, y1: 250 }, 1000, 800);

    expect(view.k).toBeCloseTo((1000 * 0.94) / 400);
    const c = toScreen(view, { x: 300, y: 150 });
    expect([c.x, c.y]).toEqual([500, 400]);
  });

  it("does not blow a small box up past the cap", () => {
    expect(fitBox({ x0: 0, y0: 0, x1: 10, y1: 10 }, 1000, 800, 1.6).k).toBe(1.6);
  });
});

describe("fitLevel", () => {
  const level = { w: 1800, h: 1000, box: [200, 100, 1000, 500] as [number, number, number, number] };

  it("centres the content box in the whole canvas, so opening a panel over it never changes the fit", () => {
    const c = toScreen(fitLevel(level, 2000, 1000), { x: 600, y: 300 });

    expect([c.x, c.y]).toEqual([1000, 500]);
  });

  it("falls back to the whole scene when the level has no content box", () => {
    const c = toScreen(fitLevel({ w: 400, h: 200 }, 1000, 1000), { x: 200, y: 100 });

    expect([c.x, c.y]).toEqual([500, 500]);
  });
});

describe("zoomAbout", () => {
  const fit: View = { k: 1, x: 0, y: 0 };

  it("keeps the world point under the cursor where it was", () => {
    const cursor = { x: 700, y: 300 };

    const zoomed = zoomAbout(fit, fit, cursor, 1.25)!;

    expect(zoomed.k).toBe(1.25);
    const [before, after] = [toWorld(fit, cursor), toWorld(zoomed, cursor)];
    expect(after.x).toBeCloseTo(before.x);
    expect(after.y).toBeCloseTo(before.y);
  });

  it("returns to the fit, not below it, when zooming out reaches it", () => {
    expect(zoomAbout({ k: 1.1, x: -50, y: -20 }, fit, { x: 0, y: 0 }, 0.5)).toBeNull();
  });
});

describe("wheelFactor", () => {
  it("zooms in on a wheel or pinch toward the screen and out away from it", () => {
    expect(wheelFactor(-3, 0, 800)).toBeGreaterThan(1);
    expect(wheelFactor(3, 0, 800)).toBeLessThan(1);
  });

  it("zooms a mouse notch as far as the approved mockup does", () => {
    expect(wheelFactor(100, 0, 800)).toBeCloseTo(Math.exp(-0.15));
  });

  it("steps a line-mode notch as far as a pixel-mode one", () => {
    expect(wheelFactor(3, 1, 800)).toBeCloseTo(wheelFactor(99, 0, 800));
  });
});

describe("refitView", () => {
  const level = { w: 2400, h: 400, box: [0, 0, 2400, 400] as [number, number, number, number] };
  const open = fitLevel(level, 1420, 1000), folded = fitLevel(level, 1618, 1000);

  it("moves a view sitting at the fit to the new fit, whether the canvas widened or narrowed", () => {
    expect(refitView(open, open, folded)).toEqual(folded);
    expect(refitView(folded, folded, open)).toEqual(open);
  });

  it("leaves a zoomed-in view where the operator put it", () => {
    const zoomed = { k: open.k * 3, x: -500, y: -80 };

    expect(refitView(zoomed, open, folded)).toBe(zoomed);
    expect(refitView({ k: folded.k * 3, x: -500, y: -80 }, folded, open).k).toBe(folded.k * 3);
  });
});
