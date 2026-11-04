// The task dialog's Markdown: a task's sections and a doc's body, drawn from the blocks `markdown` reads.
import DOMPurify from "dompurify";
import { Marked, type Token } from "marked";
import { createContext, useContext, useState } from "react";
import { Diagram } from "./Diagram";
import { CRITERIA_POINTER, opensByDefault, repoPath } from "./taskViewModel";

/** Text with each TASK-N or PROP-N id drawn as a link that opens that task in this dialog. */
export function Linked({ text, open }: { text: string; open: (id: string) => void }) {
  return <>{text.split(/((?:TASK|PROP)-\d+)/).map((part, i) => i % 2 ? (
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
function Section({ name, gist, children, open }: { name: string; gist: string; children: React.ReactNode; open: (id: string) => void }) {
  const [shown, setShown] = useState(() => storedSections()[name] ?? opensByDefault(name));
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

/** A TASK-N id in running text as a link the dialog opens (`Md` handles the click). */
const taskLink = {
  name: "task",
  level: "inline" as const,
  start: (src: string) => src.search(/TASK-\d+/),
  tokenizer: (src: string) => { const id = /^TASK-\d+/.exec(src)?.[0]; return id ? { type: "task", raw: id, id } : undefined; },
  renderer: ({ id }: { id?: string }) => `<a class="tl" href="?view=kanban&task=${id}" data-task="${id}">${id}</a>`,
};

/** marked set to draw the dialog's elements: `##` as h4, a fence as a labelled figure, an outside link in a new tab, and a file path in code as a link into `base`. */
const converter = (base: string | null) => new Marked({
  extensions: [taskLink],
  renderer: {
    heading({ tokens }) { return `<h4>${this.parser.parseInline(tokens)}</h4>`; },
    code({ text, lang }) { return `<figure class="fence"><span class="lang">${lang || "text"}</span><pre>${text.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</pre></figure>`; },
    link({ href, tokens }) { return `<a href="${href}" target="_blank" rel="noopener">${this.parser.parseInline(tokens)} ↗</a>`; },
    codespan({ text }) {
      const path = repoPath(text);
      return `<code>${path && base ? `<a class="rp" href="${base}/blob/main/${path}" target="_blank" rel="noopener">${path}</a>` : path ?? text}</code>`;
    },
  },
});

const textOf = (el: Element) => (el.textContent ?? "").replace(/\s+/g, " ").trim();

/** A section's description, plan or notes as Markdown; with `diagrams`, a mermaid fence draws as the diagram it describes (a task's own text keeps it as code); with `folds`, each `##` heading is a collapsible section in a capped pane; with `drawn`, the `start_criteria` block is a pointer to the rail. */
export function Md({ text, className = "md", drawn = false, diagrams = false, folds = false, open }: { text: string; className?: string; drawn?: boolean; diagrams?: boolean; folds?: boolean; open: (id: string) => void }) {
  const marked = converter(useContext(RepoBase));
  const html = (tokens: Token[]) => DOMPurify.sanitize(marked.parser(tokens), { ADD_ATTR: ["target"] }).replace(/<table>[\s\S]*?<\/table>/g, '<div class="tbl">$&</div>').replace(/ align="right"/g, ' class="r"');
  const draw = (tokens: Token[]) => {
    const out: React.ReactNode[] = [];
    let run: Token[] = [];
    const flush = () => { if (run.length) out.push(<div key={out.length} dangerouslySetInnerHTML={{ __html: html(run) }} />); run = []; };
    for (const t of tokens) {
      if (diagrams && t.type === "code" && t.lang === "mermaid") { flush(); out.push(<Diagram key={out.length} source={t.text} />); } else run.push(t);
    }
    flush();
    return out;
  };
  const tokens = marked.lexer(text).filter((t) => t.type !== "space").map((t): Token => drawn && t.type === "code" && /^start_criteria:/m.test(t.text)
    ? { type: "html", raw: t.raw, text: `<p class="moved">${CRITERIA_POINTER}</p>`, block: true, pre: false } : t);
  const click = (e: React.MouseEvent) => {
    const id = (e.target as Element).closest<HTMLElement>("a[data-task]")?.dataset.task;
    if (id) { e.preventDefault(); open(id); }
  };
  if (!folds) return <div className={className} onClick={click}>{draw(tokens)}</div>;
  const parts: { name: string | null; tokens: Token[] }[] = [{ name: null, tokens: [] }];
  for (const t of tokens) {
    if (t.type === "heading" && t.depth === 2) parts.push({ name: t.text, tokens: [] }); else parts[parts.length - 1].tokens.push(t);
  }
  const gist = (blocks: Token[]) => {
    const first = blocks.find((t) => t.type !== "code");
    const body = new DOMParser().parseFromString(first ? html([first]) : "", "text/html").body;
    const cells = [...body.querySelectorAll(":scope > :is(ul, ol) > li, th")];
    return cells.length ? cells.map(textOf).join(" · ") : textOf(body);
  };
  return <div className={className + " desc"} onClick={click}>{parts.filter((s) => s.name !== null || s.tokens.length).map((s, i) => s.name === null
    ? <div key={i}>{draw(s.tokens)}</div>
    : <Section key={i + s.name} name={s.name} gist={gist(s.tokens)} open={open}>{draw(s.tokens)}</Section>)}</div>;
}
