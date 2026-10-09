import { demoServer } from "../demo/demo";

/** A write says it is JSON, body or none: starpulse._internal.api.server refuses any other, which a web page on another site cannot send without asking first. */
const asJson = (init?: RequestInit): RequestInit | undefined => {
  if (!init?.method || init.method === "GET") return init;
  const headers = new Headers(init.headers);
  if (!headers.has("content-type")) headers.set("content-type", "application/json");
  return { ...init, headers };
};

/** `fetch` for the page's /api requests: answered by the demo server on a demo page, by starpulse._internal.api.server otherwise. */
export const apiFetch = (url: string, init?: RequestInit): Promise<Response> => demoServer()?.fetch(url, init) ?? fetch(url, asJson(init));
