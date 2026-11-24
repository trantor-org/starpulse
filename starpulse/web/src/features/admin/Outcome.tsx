import type { Saved } from "./adminSettings";

/** What a change to the shared settings came to: kept for every device, or refused with the server's reason. */
export function Outcome({ saved }: { saved: Saved }) {
  if (saved.kind === "saved") return <div className="ok">Saved for every device</div>;
  if (saved.kind === "refused") return <><div className="refusal"><div className="k">the server refused the change</div>{saved.reason}</div><div className="no">Not saved.</div></>;
  return null;
}
