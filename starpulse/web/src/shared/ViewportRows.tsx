import { createContext, useCallback, useContext, useEffect, useRef, useState, type CSSProperties, type Dispatch, type HTMLAttributes, type ReactNode, type SetStateAction } from "react";
import { useViewActive } from "./Kept";

type Show = Dispatch<SetStateAction<boolean>>;
type Register = (node: HTMLElement, show: Show) => () => void;
const Rows = createContext<Register | null>(null);

/** A scrolling box that mounts a row's contents only while its placeholder is in the viewport or its overscan. */
export function Viewport({ rootMargin = "320px 0px", children, ...props }: HTMLAttributes<HTMLDivElement> & { rootMargin?: string }) {
  const active = useViewActive();
  const root = useRef<HTMLDivElement>(null);
  const rows = useRef(new Map<HTMLElement, Show>());
  const observer = useRef<IntersectionObserver | null>(null);
  const register = useCallback<Register>((node, show) => {
    rows.current.set(node, show);
    observer.current?.observe(node);
    return () => {
      observer.current?.unobserve(node);
      rows.current.delete(node);
    };
  }, []);
  useEffect(() => {
    if (!active || typeof IntersectionObserver === "undefined") return;
    let activated = false;
    const watching = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) activated = true;
      if (!activated) return; // a hidden warmed view keeps its initial rows until its first reveal
      for (const entry of entries) rows.current.get(entry.target as HTMLElement)?.(entry.isIntersecting);
    }, { root: root.current, rootMargin });
    observer.current = watching;
    for (const node of rows.current.keys()) watching.observe(node);
    return () => {
      observer.current = null;
      watching.disconnect();
    };
  }, [active, rootMargin]);
  return <Rows value={register}><div ref={root} {...props}>{children}</div></Rows>;
}

/** The light placeholder retained for an unmounted row keeps the scroll range stable at its estimated height. */
export function ViewportRow({ initial, estimate, force = false, children }: { initial: boolean; estimate: number; force?: boolean; children: ReactNode }) {
  const register = useContext(Rows);
  const row = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(initial);
  useEffect(() => {
    const node = row.current;
    return node && register ? register(node, setNear) : undefined;
  }, [register]);
  const shown = near || force;
  return (
    <div ref={row} className="viewport-row" data-viewport-row="" style={shown ? undefined : { minBlockSize: estimate } as CSSProperties}>
      {shown ? children : null}
    </div>
  );
}
