// The skill a phase machine runs, read from the submachine link that opens it: the one place both views take a skill's name from.
import type { Sky } from "./sky";

/** The skill the submachine link opening `machine` declares, in any flow; undefined when no link opens it or its link names none. */
export function skillOf(flows: Sky["flows"], machine: string): string | undefined {
  for (const flow of Object.values(flows))
    for (const link of flow.machine.submachines ?? []) if (link.machine === machine && link.skill) return link.skill;
  return undefined;
}
