// A session's nickname: an adjective and an animal seeded by its id, so a held card's holder reads as `silly-badger`
// rather than five hash characters, and the same session gets the same name on every card and reload.
import { adjectives, animals, uniqueNamesGenerator } from "unique-names-generator";

/** A cloud session's URL, or a local session's bare UUID. */
const SESSION = /^(?:https?:\/\/\S*?\/session_(\w+)|([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}))$/i;

/** 32-bit FNV-1a finished with murmur3's fmix32. The library hashes a string seed by summing its character codes, so
 * anagrams and ids differing by +1/-1 in two places collide; a numeric seed skips that. */
function fnv1a(s: string) {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 0x01000193);
  h = Math.imul(h ^ (h >>> 16), 0x85ebca6b);
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35);
  return (h ^ (h >>> 16)) >>> 0;
}

/** The nickname of a session holder, or null when the assignee is not a session URL or UUID (a profile, `local`, unheld). */
export function sessionNickname(assignee: string): string | null {
  const match = SESSION.exec(assignee);
  const id = match?.[1] ?? match?.[2];
  if (!id) return null;
  return uniqueNamesGenerator({ dictionaries: [adjectives, animals], separator: "-", style: "lowerCase", seed: fnv1a(id) });
}
