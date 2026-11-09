/** What a filter menu lists: each value the drawn tasks carry and how many carry it. */
export interface Option {
  value: string;
  count: number;
}

/** One of the Assignee or Milestone menus: each value with its count; the chosen one is picked again to clear it. */
export function ChoiceMenu({ title, options, value, name, set, close }: {
  title: string; options: Option[]; value: string | null; name: (v: string) => string; set: (v: string | null) => void; close: () => void;
}) {
  return (
    <>
      <div className="scrim" onClick={close} />
      <div className="menu" role="menu">
        <div className="hd">{title}</div>
        {options.map((o) => (
          <button key={o.value} role="menuitemradio" aria-checked={o.value === value} className={o.value === value ? "on" : undefined}
            onClick={() => { set(o.value === value ? null : o.value); close(); }}>{name(o.value)}<span>{o.count}</span></button>
        ))}
      </div>
    </>
  );
}
