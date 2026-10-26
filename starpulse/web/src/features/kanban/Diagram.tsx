// A mermaid fence drawn as its diagram. mermaid is large, so it loads (a chunk of its own) the first time a doc with a diagram opens, never with the page.
import { useEffect, useState } from "react";

/** The page's colors as mermaid's theme takes them: the stylesheet's `:root` tokens, read when a diagram draws. */
function themeVariables(): Record<string, string> {
  const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return {
    background: token("--code"), primaryColor: token("--stack"), primaryBorderColor: token("--agent"), primaryTextColor: token("--ink-2"),
    lineColor: token("--slate-4"), secondaryColor: token("--stack"), tertiaryColor: token("--stack"), textColor: token("--ink-2"),
    fontFamily: "Inter, sans-serif",
  };
}

let drawn = 0;

/** `source` as an SVG; rejects when mermaid cannot read it. */
async function drawDiagram(source: string): Promise<string> {
  const { default: mermaid } = await import("mermaid");
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "base", themeVariables: themeVariables() });
  const id = `mmd-${++drawn}`;
  try {
    return (await mermaid.render(id, source)).svg;
  } finally {
    document.getElementById(`d${id}`)?.remove(); // a failed render leaves its error drawing in the body
  }
}

type Drawn = { source: string; svg: string } | { source: string; failed: true };

export function Diagram({ source }: { source: string }) {
  const [drawn, setDrawn] = useState<Drawn | null>(null);
  useEffect(() => {
    let live = true;
    drawDiagram(source).then((svg) => live && setDrawn({ source, svg }), () => live && setDrawn({ source, failed: true }));
    return () => { live = false; };
  }, [source]);
  const drawing = drawn?.source === source ? drawn : null; // a drawing of an earlier source is not this one's
  if (drawing && "failed" in drawing) return <figure className="fence"><span className="lang">mermaid</span><pre>{source}</pre></figure>;
  return (
    <figure className="fence mm" aria-busy={!drawing}>
      <span className="lang">mermaid</span>
      {drawing ? <div className="mmd" role="img" aria-label="Diagram" dangerouslySetInnerHTML={{ __html: drawing.svg }} /> : <span className="none">Drawing diagram…</span>}
    </figure>
  );
}
