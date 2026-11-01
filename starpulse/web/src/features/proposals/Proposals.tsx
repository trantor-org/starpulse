// The Proposals view: the tasks agents proposed and the operator has not yet decided. Each row shows the title, why, filing session
// and duplicate resolution; Promote moves it to Ready under the chosen profile and Drop archives it. Proposed tasks are drawn here
// and never on the Kanban.
import { useEffect, useState } from "react";
import { apiFetch } from "../../api/apiFetch";
import type { Roles } from "../../api";
import type { KanbanTask } from "../kanban/kanbanModel";
import type { Reply } from "../kanban/move";
import { dropProposal, promoteProposal, proposedOf, sectionsOf } from "./proposalsModel";

/** The part of a task's full record a proposal row reads; the snapshot slims the description off. */
interface Detail {
  description: string;
  profile: string;
  createdBy: string;
}

interface Props {
  cards: KanbanTask[];
  roles: Roles;
  profiles: string[];
  fetcher?: typeof apiFetch;
}

const detailOf = (record: Partial<Detail> | null | undefined): Detail | null =>
  record ? { description: record.description ?? "", profile: record.profile ?? "", createdBy: record.createdBy ?? "" } : null;

export function Proposals({ cards, roles, profiles, fetcher = apiFetch }: Props) {
  const proposals = proposedOf(cards, roles);
  const ids = proposals.map((p) => p.id).join(" ");
  const [details, setDetails] = useState<Record<string, Detail>>({});
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [refused, setRefused] = useState<Record<string, string>>({});

  useEffect(() => {
    let live = true;
    const missing = ids.split(" ").filter((id) => id && !details[id]);
    void (async () => {
      for (const id of missing) {
        const detail = await fetcher(`/api/task/${encodeURIComponent(id)}`)
          .then((r) => (r.ok ? r.json() : null))
          .then((body: { record?: Partial<Detail> | null } | null) => detailOf(body?.record))
          .catch(() => null);
        if (live && detail) setDetails((d) => ({ ...d, [id]: detail }));
      }
    })();
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fetch for ids that appear, not again for each detail that lands
  }, [ids, fetcher]);

  const decide = async (id: string, act: () => Promise<Reply>) => {
    setBusy((b) => ({ ...b, [id]: true }));
    setRefused(({ [id]: _gone, ...rest }) => rest);
    const reply = await act();
    if (reply.ok) return;
    setBusy((b) => ({ ...b, [id]: false }));
    setRefused((r) => ({ ...r, [id]: reply.reason }));
  };

  return (
    <div id="proposals">
      <div className="hd">
        <span className="ttl">Proposals</span>
        <span className="ct">{proposals.length}</span>
      </div>
      {proposals.length === 0 && <p className="none">No proposals</p>}
      {proposals.map((p) => {
        const detail = details[p.id];
        const { why, duplicate } = sectionsOf(detail?.description ?? p.description ?? "");
        const current = detail?.profile ?? p.profile ?? "";
        const profile = chosen[p.id] ?? current;
        const options = profile && !profiles.includes(profile) ? [profile, ...profiles] : profiles;
        return (
          <section className="prop" key={p.id} data-task={p.id}>
            <h2><span className="id">{p.id}</span> {p.title}</h2>
            {why && <p className="why">{why}</p>}
            <dl>
              <dt>Filed by</dt>
              <dd>{detail?.createdBy || "unknown"}</dd>
              <dt>Duplicates</dt>
              <dd>{duplicate || "none recorded"}</dd>
            </dl>
            <div className="act">
              <select aria-label={`Profile for ${p.id}`} value={profile} disabled={busy[p.id]}
                onChange={(e) => setChosen((c) => ({ ...c, [p.id]: e.target.value }))}>
                <option value="">No profile</option>
                {options.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
              <button type="button" className="btn go" disabled={busy[p.id]}
                onClick={() => void decide(p.id, () => promoteProposal(p.id, profile, current, roles, fetcher))}>Promote</button>
              <button type="button" className="btn" disabled={busy[p.id]}
                onClick={() => void decide(p.id, () => dropProposal(p.id, roles, fetcher))}>Drop</button>
            </div>
            {refused[p.id] && <p className="refused" role="alert">{refused[p.id]}</p>}
          </section>
        );
      })}
    </div>
  );
}
