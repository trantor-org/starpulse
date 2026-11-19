/** A write says it is JSON, body or none: starpulse.runtime.server refuses any other, which a web page on another site cannot send without asking first. */
const asJson = (init?: RequestInit): RequestInit | undefined => {
  if (!init?.method || init.method === "GET") return init;
  const headers = new Headers(init.headers);
  if (!headers.has("content-type")) headers.set("content-type", "application/json");
  return { ...init, headers };
};

/** Who the page's writes name as their actor: a write that names none is recorded as anonymous, never as the operator. */
export const PAGE_ACTOR = "operator";

/** `fetch` for the page's /api requests, answered by starpulse.runtime.server (the public demo's recording on a replay page). */
export const apiFetch = (url: string, init?: RequestInit): Promise<Response> => fetch(url, asJson(init));
