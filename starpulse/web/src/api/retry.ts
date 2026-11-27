// How long the page waits before it reopens a connection that dropped.

/** The longest the page waits before it reopens a connection that has not opened since it dropped. */
export const RETRY_CAP_MS = 3000;
/** How long a connection stays down before the page calls it lost; it goes on retrying. */
export const LOST_MS = 20_000;
/** A subscription that sends no byte for this long is cut: the server pings each one every 15 s, so silence this long is a connection gone quiet without closing. */
export const QUIET_MS = 35_000;
/** The wait before the `attempt`th reopen of a dropped connection: none for the first, then 250 ms doubling to the cap. */
export const retryWait = (attempt: number) => (attempt === 0 ? 0 : Math.min(RETRY_CAP_MS, 250 * 2 ** (attempt - 1)));
