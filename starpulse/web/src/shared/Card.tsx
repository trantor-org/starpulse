import type { ReactNode } from "react";

/** A card in the navigator: its body scrolls inside it, so the navigator never does. */
export function Card({ title, id, children }: { title: string; id?: string; children: ReactNode }) {
  return (
    <section className="away card">
      <h3>{title}</h3>
      <div className="body" id={id}>{children}</div>
    </section>
  );
}
