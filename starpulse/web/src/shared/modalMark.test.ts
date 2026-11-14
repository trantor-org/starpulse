// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MODAL_DRAWN, watchModalMarks } from "./modalMark";

let stop = () => {};
const mark = vi.fn();

beforeEach(() => {
  mark.mockClear();
  vi.stubGlobal("requestAnimationFrame", (run: () => void) => (run(), 0));
  Object.defineProperty(performance, "mark", { value: mark, configurable: true, writable: true });
  document.body.innerHTML = "";
  stop = watchModalMarks();
});
afterEach(() => {
  stop();
  vi.unstubAllGlobals();
});

const open = (html: string) => {
  const host = document.createElement("div");
  host.innerHTML = html;
  document.body.append(host);
  return host;
};
const flush = () => new Promise((done) => setTimeout(done));

it("marks a dialog with its label once it is in the page", async () => {
  open('<div role="dialog" aria-label="New task"></div>');
  await flush();
  expect(mark).toHaveBeenCalledExactlyOnceWith(MODAL_DRAWN, { detail: { label: "New task" } });
});

it("waits out aria-busy and marks the dialog once", async () => {
  const host = open('<div role="dialog" aria-label="TASK-1 x" aria-busy="true"></div>');
  await flush();
  expect(mark).not.toHaveBeenCalled();
  host.firstElementChild!.setAttribute("aria-busy", "false");
  await flush();
  host.firstElementChild!.setAttribute("aria-busy", "false");
  await flush();
  expect(mark).toHaveBeenCalledTimes(1);
});

it("leaves a dialog drawn ahead under an inert or hidden ancestor unmarked until it shows", async () => {
  const host = open('<div inert><div role="dialog" aria-label="Drawn ahead"></div></div>');
  await flush();
  expect(mark).not.toHaveBeenCalled();
  host.firstElementChild!.removeAttribute("inert");
  await flush();
  expect(mark).toHaveBeenCalledTimes(1);
});

it("marks a dialog opened again as a new element", async () => {
  open('<div role="dialog" aria-label="A"></div>');
  await flush();
  document.body.innerHTML = "";
  open('<div role="dialog" aria-label="A"></div>');
  await flush();
  expect(mark).toHaveBeenCalledTimes(2);
});
