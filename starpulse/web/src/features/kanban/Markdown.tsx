// The task dialog's Markdown: a task's sections and a doc's body, drawn from the blocks `markdown` reads.
import { createContext, useContext, useState } from "react";
import { Diagram } from "./Diagram";
import { markdown, opensByDefault, preview, repoPath, sections, type Block } from "./taskViewModel";

/** Text with each TASK-N id drawn as a link that opens that task in this dialog. */
export function Linked({ text, open }: { text: string; open: (id: string) => void }) {
  return <>{text.split(/(TASK-\d+)/).map((part, i) => i % 2 ? (
    <a key={i} className="tl" href={`?view=kanban&task=${part}`} onClick={(e) => { e.preventDefault(); open(part); }}>{part}</a>
  ) : part)}</>;
}

/** The repository page the dialog's file paths link into (its task's first pull request's), or null for none. */
export const RepoBase = createContext<string | null>(null);

/** Text with the inline Markdown a task row, section or doc body draws: `code`, **bold**, [links](url) and TASK-N ids. */
export function Inline({ text, open }: { text: string; open: (id: string) => void }) {
  const base = useContext(RepoBase);
  return <>{text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\(https?:[^)]+\))/).map((part, i) => {
    if (i % 2 === 0) return <Linked key={i} text={part} open={open} />;
    if (part.startsWith("`")) {
      const code = part.slice(1, -1);
      const path = repoPath(code);
      if (!path) return <code key={i}>{code}</code>;
      return <code key={i}>{base ? <a className="rp" href={base + "/blob/main/" + path} target="_blank" rel="noopener">{path}</a> : path}</code>;
    }
    if (part.startsWith("**")) return <strong key={i}><Linked text={part.slice(2, -2)} open={open} /></strong>;
    const [, label, href] = /^\[(.+)\]\((.+)\)$/.exec(part)!;
    return <a key={i} href={href} target="_blank" rel="noopener"><Inline text={label} open={open} /> ↗</a>;
  })}</>;
}

/** The browser key holding which description sections the reader opened or closed, by heading name. */
export const SECTIONS_KEY = "fv.task.sections";

function storedSections(): Record<string, boolean> {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(SECTIONS_KEY) ?? "{}");
    return typeof raw === "object" && raw !== null ? raw as Record<string, boolean> : {};
  } catch {
    return {};
  }
}

function keepSection(name: string, open: boolean) {
  try {
    localStorage.setItem(SECTIONS_KEY, JSON.stringify({ ...storedSections(), [name]: open }));
  } catch { /* storage is a convenience: a blocked write leaves the section as it is */ }
}

/** One `##` section as a toggle row (open or closed as the reader last left it) over its blocks; a closed one shows a one-line preview. */
function Section({ name, blocks, children, open }: { name: string; blocks: Block[]; children: React.ReactNode; open: (id: string) => void }) {
  const [shown, setShown] = useState(() => storedSections()[name] ?? opensByDefault(name));
  const gist = preview(blocks);
  return (
    <details className="dsec" data-section={name} open={shown} onToggle={(e) => {
      const now = e.currentTarget.open;
      if (now !== shown) { setShown(now); keepSection(name, now); }
    }}>
      <summary><span className="car"></span><span className="ht"><Inline text={name} open={open} /></span>{gist && <span className="pv">{gist}</span>}</summary>
      <div className="db">{children}</div>
    </details>
  );
}

/** A section's description, plan or notes as Markdown blocks; with `diagrams`, a mermaid fence draws as the diagram it describes (a task's own text keeps it as code); with `folds`, each `##` heading is a collapsible section in a capped pane. */
export function Md({ text, className = "md", drawn = false, diagrams = false, folds = false, open }: { text: string; className?: string; drawn?: boolean; diagrams?: boolean; folds?: boolean; open: (id: string) => void }) {
  const at = (t: string) => <Inline text={t} open={open} />;
  const items = (list: string[]) => list.map((t, i) => <li key={i}>{at(t)}</li>);
  const draw = (blocks: Block[]) => blocks.map((b, i) => {
    if (b.kind === "table") return (
      <div key={i} className="tbl"><table>
        <thead><tr>{b.head.map((c, j) => <th key={j} className={b.right[j] ? "r" : undefined}>{at(c)}</th>)}</tr></thead>
        <tbody>{b.rows.map((row, j) => <tr key={j}>{row.map((c, k) => <td key={k} className={b.right[k] ? "r" : undefined}>{at(c)}</td>)}</tr>)}</tbody>
      </table></div>
    );
    if (b.kind === "list") {
      const List = b.ordered ? "ol" : "ul";
      return <List key={i}>{b.items.map((item, j) => {
        const Sub = item.sub?.ordered ? "ol" : "ul";
        return <li key={j}>{at(item.text)}{item.sub && <Sub>{items(item.sub.items)}</Sub>}</li>;
      })}</List>;
    }
    if (b.kind === "h") return <h4 key={i}>{at(b.text)}</h4>;
    if (b.kind === "pre" && diagrams && b.lang === "mermaid") return <Diagram key={i} source={b.text} />;
    if (b.kind === "pre") return <figure key={i} className="fence"><span className="lang">{b.lang || "text"}</span><pre>{b.text}</pre></figure>;
    return <p key={i} className={b.kind === "moved" ? "moved" : undefined}>{at(b.text)}</p>;
  });
  const blocks = markdown(text, drawn);
  if (!folds) return <div className={className}>{draw(blocks)}</div>;
  return <div className={className + " desc"}>{sections(blocks).map((s, i) => s.name === null
    ? <div key={i}>{draw(s.blocks)}</div>
    : <Section key={i + s.name} name={s.name} blocks={s.blocks} open={open}>{draw(s.blocks)}</Section>)}</div>;
}
