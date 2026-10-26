// The task dialog's Markdown: a task's sections and a doc's body, drawn from the blocks `markdown` reads.
import { Diagram } from "./Diagram";
import { markdown } from "./taskViewModel";

/** Text with each TASK-N id drawn as a link that opens that task in this dialog. */
export function Linked({ text, open }: { text: string; open: (id: string) => void }) {
  return <>{text.split(/(TASK-\d+)/).map((part, i) => i % 2 ? (
    <a key={i} className="tl" href={`?view=kanban&task=${part}`} onClick={(e) => { e.preventDefault(); open(part); }}>{part}</a>
  ) : part)}</>;
}

/** A section's description, plan or notes as Markdown blocks; with `diagrams`, a mermaid fence draws as the diagram it describes (a task's own text keeps it as code). */
export function Md({ text, className = "md", drawn = false, diagrams = false, open }: { text: string; className?: string; drawn?: boolean; diagrams?: boolean; open: (id: string) => void }) {
  const at = (t: string) => <Linked text={t} open={open} />;
  return <div className={className}>{markdown(text, drawn).map((b, i) => {
    if (b.kind === "table") return (
      <div key={i} className="tbl"><table>
        <thead><tr>{b.head.map((c, j) => <th key={j} className={b.right[j] ? "r" : undefined}>{at(c)}</th>)}</tr></thead>
        <tbody>{b.rows.map((row, j) => <tr key={j}>{row.map((c, k) => <td key={k} className={b.right[k] ? "r" : undefined}>{at(c)}</td>)}</tr>)}</tbody>
      </table></div>
    );
    if (b.kind === "h") return <h4 key={i}>{at(b.text)}</h4>;
    if (b.kind === "pre" && diagrams && b.lang === "mermaid") return <Diagram key={i} source={b.text} />;
    if (b.kind === "pre") return <figure key={i} className="fence"><span className="lang">{b.lang || "text"}</span><pre>{b.text}</pre></figure>;
    return <p key={i} className={b.kind === "moved" ? "moved" : undefined}>{at(b.text)}</p>;
  })}</div>;
}
