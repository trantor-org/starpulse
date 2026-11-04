// The Proposals view: the tasks agents proposed and the operator has not yet decided, in two sections by the triage marker
// (Pre-approved, then Unapproved), each a tier list: one row per priority, milestone or kind, a horizontal strip of cards.
// Search draws in the navigator's left panel. Each card shows the title, why, kind, size, profile and
// model, the triage verdict with its reason, filing session and duplicate resolution; Promote moves it to Ready under the chosen
// profile and Drop archives it. Proposed tasks are drawn here and never on the Kanban.
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { apiFetch } from "../../api/apiFetch";
import { SearchClear } from "../../shared/SearchClear";
import type { Roles } from "../../api";
import type { KanbanTask } from "../kanban/kanbanModel";
import type { Reply } from "../kanban/move";
import { NO_HARNESSES, type Harnesses } from "../kanban/start";
import type { TaskComment } from "../kanban/taskViewModel";
import {
  dropProposal, groupsOf, isPreapproved, kindOf, matchesQuery, modelOf, promoteProposal, proposedOf, sectionsOf, sizeOf, verdictOf,
  type GroupBy, type SortBy,
} from "./proposalsModel";

/** The part of a task's full record a proposal card reads; the snapshot slims the description off and carries no priority. */
interface Detail {
  description: string;
  profile: string;
  createdBy: string;
  priority: string;
  comments: TaskComment[];
}

interface Props {
  cards: KanbanTask[];
  roles: Roles;
  profiles: string[];
  harnesses?: Harnesses;
  /** The navigator's search slot: where the search box draws, in the left panel; the view's own header holds it when there is none or the panel is hidden. */
  searchSlot?: HTMLElement | null;
  fetcher?: typeof apiFetch;
}

const detailOf = (record: Partial<Detail> | null | undefined): Detail | null =>
  record
    ? {
        description: record.description ?? "", profile: record.profile ?? "", createdBy: record.createdBy ?? "",
        priority: (record.priority ?? "").toLowerCase(), comments: record.comments ?? [],
      }
    : null;

const SECTIONS = [
  { key: "preapproved", title: "Pre-approved", empty: "Nothing pre-approved" },
  { key: "unapproved", title: "Unapproved", empty: "Nothing awaiting triage" },
] as const;

export function Proposals({ cards, roles, profiles, harnesses = NO_HARNESSES, searchSlot = null, fetcher = apiFetch }: Props) {
  const proposals = proposedOf(cards, roles);
  const ids = proposals.map((p) => p.id).join(" ");
  const [details, setDetails] = useState<Record<string, Detail>>({});
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [refused, setRefused] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const [by, setBy] = useState<GroupBy>("priority");
  const [sort, setSort] = useState<SortBy>("newest");
  const searchBox = useRef<HTMLInputElement>(null);

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

  const shown = proposals.filter((p) => matchesQuery(p, query, details[p.id]?.description ?? p.description));

  const card = (p: KanbanTask) => {
    const detail = details[p.id];
    const { why, duplicate } = sectionsOf(detail?.description ?? p.description ?? "");
    const current = detail?.profile || p.profile || "";
    const profile = chosen[p.id] ?? current;
    const options = profile && !profiles.includes(profile) ? [profile, ...profiles] : profiles;
    const model = modelOf(current, harnesses);
    const kind = kindOf(p.labels);
    const size = sizeOf(p.labels);
    const verdict = verdictOf(detail?.comments);
    return (
      <article className={`prop${isPreapproved(p) ? " ok" : ""}`} key={p.id} data-task={p.id}>
        <h4><span className="id">{p.id}</span> {p.title}</h4>
        <div className="chips">
          {kind && <span className="chip kind">{kind}</span>}
          {size && <span className="chip size">size {size}</span>}
          {detail?.priority && <span className={`chip pri ${detail.priority}`}>{detail.priority}</span>}
          <span className={`chip profile${current ? "" : " none"}`}>{current || "no profile"}</span>
          {model && <span className="chip model">{model}</span>}
        </div>
        <div className={`verdict${isPreapproved(p) ? " ok" : ""}`}>
          <span className="vd">{isPreapproved(p) ? "Pre-approved" : "Not triaged"}</span>
          {verdict && <span className="vr">{verdict}</span>}
        </div>
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
            onClick={() => void decide(p.id, () => promoteProposal(p.id, profile, current, roles, fetcher, p.openDeps))}>Promote</button>
          <button type="button" className="btn" disabled={busy[p.id]}
            onClick={() => void decide(p.id, () => dropProposal(p.id, roles, fetcher))}>Drop</button>
        </div>
        {refused[p.id] && <p className="refused" role="alert">{refused[p.id]}</p>}
      </article>
    );
  };

  const searchInput = (
    <input type="search" id="ppq" ref={searchBox} aria-label="Search proposals" placeholder="Search title, description, ID" autoComplete="off" spellCheck={false}
      value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setQuery("")} />
  );

  return (
    <div id="proposals">
      {searchSlot && createPortal(
        <div className="fw">{searchInput}<SearchClear input={searchBox} value={query} clear={() => setQuery("")} /></div>,
        searchSlot,
      )}
      <div className="hd">
        <h1 className="ttl">Proposals</h1>
        <span className="ct">{proposals.length}</span>
        <div className="tools">
          {!searchSlot && searchInput}
          {searchSlot && (
            <input type="search" className="mq" aria-label="Search proposals" placeholder="Search title, description, ID" autoComplete="off" spellCheck={false}
              value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setQuery("")} />
          )}
          <select aria-label="Group by" value={by} onChange={(e) => setBy(e.target.value as GroupBy)}>
            <option value="none">No grouping</option>
            <option value="milestone">Group by milestone</option>
            <option value="priority">Group by priority</option>
            <option value="kind">Group by kind</option>
          </select>
          <select aria-label="Sort by" value={sort} onChange={(e) => setSort(e.target.value as SortBy)}>
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="priority">Priority</option>
          </select>
        </div>
      </div>
      {proposals.length === 0 && <p className="none">No proposals</p>}
      {proposals.length > 0 && shown.length === 0 && <p className="none">No proposals match</p>}
      {shown.length > 0 && SECTIONS.map(({ key, title, empty }) => {
        const inSection = shown.filter((p) => isPreapproved(p) === (key === "preapproved"));
        return (
          <section className={`sec ${key}`} key={key} data-section={key}>
            <div className="sh"><h2>{title}</h2><span className="ct">{inSection.length}</span></div>
            {inSection.length === 0 && <p className="none">{empty}</p>}
            {groupsOf(inSection, by, sort, details).map((g) => (
              <div className={`group${g.label ? "" : " flat"}`} key={g.label}>
                {g.label && <h3 className="grp"><span className="lb">{g.label}</span><span className="ct">{g.cards.length}</span></h3>}
                <div className="strip">{g.cards.map(card)}</div>
              </div>
            ))}
          </section>
        );
      })}
    </div>
  );
}
