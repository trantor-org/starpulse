// The task view's Docs: the rail rows for a task's milestone, spec and linked docs, and the reader that draws one in the dialog's place.
import { useEffect, useState } from "react";
import { Md } from "./Markdown";
import { docLinks, fetchDoc, fetchDocs, fetchMilestone, type DocLink, type DocSummary, type MilestoneDoc, type TaskRecord } from "./taskViewModel";

type Loaded = { milestone: MilestoneDoc | null; docs: DocSummary[] };

/** The Docs rows for `record` and the milestone they open, read once the task has a milestone or a linked doc; a read the board refuses leaves its rows closed. */
export function useDocs(record: Pick<TaskRecord, "milestone" | "documentation">): { links: DocLink[]; milestone: MilestoneDoc | null } {
  const [loaded, setLoaded] = useState<Loaded>({ milestone: null, docs: [] });
  const { milestone } = record;
  const linked = Boolean(record.documentation?.length);
  useEffect(() => {
    if (!milestone && !linked) return;
    let live = true;
    void Promise.all([milestone ? fetchMilestone(milestone) : null, fetchDocs()]).then(([found, docs]) => live && setLoaded({ milestone: found, docs }));
    return () => { live = false; };
  }, [milestone, linked]);
  return { links: docLinks(record, loaded.milestone, loaded.docs), milestone: loaded.milestone };
}

/** One row per link; an openable row opens its doc in the reader and the open one is marked current. */
export function DocRows({ links, reading, open }: { links: DocLink[]; reading: string | null; open: (link: DocLink) => void }) {
  return <div className="docs">{links.map((link) => {
    const label = <><span className="kd">{link.kind}</span><span className="tt">{link.id && <b>{link.id}</b>}{link.title !== link.id && link.title}</span></>;
    return link.openable ? (
      <a key={`${link.kind} ${link.id}`} className="doc" href="#" aria-current={reading === link.id ? "true" : undefined}
        onClick={(e) => { e.preventDefault(); open(link); }}>{label}</a>
    ) : <div key={`${link.kind} ${link.id} ${link.title}`} className="doc">{label}</div>;
  })}</div>;
}

/** The text of `link`'s doc: the milestone's description, else the doc's body read from the board; null while it loads, "" when it cannot be read. */
function useBody(link: DocLink, milestone: MilestoneDoc | null): string | null {
  const [read, setRead] = useState<{ id: string; body: string } | null>(null);
  const own = link.kind === "Milestone";
  useEffect(() => {
    if (own) return;
    let live = true;
    void fetchDoc(link.id).then((doc) => live && setRead({ id: link.id, body: doc?.body ?? "" }));
    return () => { live = false; };
  }, [own, link.id]);
  if (own) return milestone?.description ?? "";
  return read?.id === link.id ? read.body : null;
}

/** A doc in the dialog's place, drawn by the same Markdown as a task's body with its mermaid fences as diagrams; Back returns to the task. */
export function DocReader({ link, milestone, back, open }: { link: DocLink; milestone: MilestoneDoc | null; back: () => void; open: (id: string) => void }) {
  const body = useBody(link, milestone)?.replace(/^# .*\n+/, ""); // the title bar already names the doc
  return (
    <>
      <div className="docbar"><button className="cancelbtn" onClick={back}>← Back to task</button><span className="kd">{link.kind}</span><b>{link.id}</b></div>
      <div className="doctitle">{link.title}</div>
      {body === null ? <span className="none">Loading…</span> : body ? <Md text={body} diagrams open={open} /> : <span className="none">This doc has no text to show.</span>}
    </>
  );
}
