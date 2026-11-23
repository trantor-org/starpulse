/** Names the page to the server, so its latency metric's `caller` label splits the page from the CLI and other readers. */
const CLIENT_HEADER = "X-StarPulse-Client";

/** Every request names the page; a write also says it is JSON, body or none: starpulse.runtime.server refuses any other, which a web page on another site cannot send without asking first. */
const named = (init?: RequestInit): RequestInit => {
  const headers = new Headers(init?.headers);
  headers.set(CLIENT_HEADER, "web");
  if (init?.method && init.method !== "GET" && !headers.has("content-type")) headers.set("content-type", "application/json");
  return { ...init, headers };
};

/** Who the page's writes name as their actor: a write that names none is recorded as anonymous, never as the operator. */
export const PAGE_ACTOR = "operator";

/** `fetch` for the page's /api requests, answered by starpulse.runtime.server (the public demo's recording on a replay page). */
export const apiFetch = (url: string, init?: RequestInit): Promise<Response> => fetch(url, named(init));
