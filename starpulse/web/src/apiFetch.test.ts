import { afterEach, expect, test, vi } from "vitest";
import { apiFetch } from "./demo";

afterEach(() => vi.unstubAllGlobals());

function stubbedFetch() {
  const fetcher = vi.fn<typeof fetch>(async () => new Response("{}"));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

const sentType = (fetcher: ReturnType<typeof stubbedFetch>) => new Headers(fetcher.mock.calls[0][1]?.headers).get("content-type");

test.each(["POST", "PUT", "DELETE"])("a %s with no body still says it is JSON, which the server requires of every write", async (method) => {
  const fetcher = stubbedFetch();
  await apiFetch("/api/run/dagu/nightly", { method });
  expect(sentType(fetcher)).toBe("application/json");
});

test("a write's own content type is kept", async () => {
  const fetcher = stubbedFetch();
  await apiFetch("/api/tasks", { method: "POST", headers: { "content-type": "application/json; charset=utf-8" }, body: "{}" });
  expect(sentType(fetcher)).toBe("application/json; charset=utf-8");
});

test("a read is sent as it is", async () => {
  const fetcher = stubbedFetch();
  await apiFetch("/api/snapshot");
  expect(fetcher).toHaveBeenCalledWith("/api/snapshot", undefined);
});
