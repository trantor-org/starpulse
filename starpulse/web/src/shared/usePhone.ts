import { useSyncExternalStore } from "react";
import { onPhone, PHONE } from "./nav";

const watch = (notify: () => void) => {
  const query = window.matchMedia?.(PHONE);
  query?.addEventListener("change", notify);
  return () => query?.removeEventListener("change", notify);
};

/** Whether the page is at phone width, following the window as it resizes. */
export const usePhone = () => useSyncExternalStore(watch, onPhone, () => false);
