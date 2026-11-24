import { apiFetch } from "./apiFetch";

/** One open task's `fields` from POST /graphql; `null` when the read is refused, the task is not open or the query answers an error. */
export async function taskQuery<T>(task: string, fields: string, fetcher: typeof apiFetch = apiFetch, signal?: AbortSignal): Promise<T | null> {
  const response = await fetcher("/graphql", {
    method: "POST",
    signal,
    body: JSON.stringify({ query: `query($id: ID!) { task(id: $id) { ${fields} } }`, variables: { id: task } }),
  });
  if (!response.ok) return null;
  const body: { data?: { task?: T | null }; errors?: unknown[] } | null = await response.json().catch(() => null);
  return body?.errors?.length ? null : (body?.data?.task ?? null);
}
