// A session's nickname: an adjective and an animal picked by a hash of its id, so a held card's holder reads as
// `silly-badger` rather than five hash characters, and the same session gets the same name on every card and reload.

const ADJECTIVES = [
  "amber", "bold", "brave", "brisk", "calm", "clever", "cosmic", "crisp", "curious", "dapper", "daring", "dizzy",
  "eager", "fancy", "fearless", "fluffy", "frosty", "fuzzy", "gentle", "giddy", "glossy", "golden", "grumpy", "happy",
  "hasty", "humble", "jolly", "jumpy", "keen", "lucky", "mellow", "merry", "mighty", "misty", "nimble", "noble",
  "peppy", "plucky", "polite", "proud", "quick", "quiet", "quirky", "rapid", "rusty", "salty", "sassy", "shiny",
  "silly", "sleepy", "sly", "snappy", "snowy", "sneaky", "spicy", "sunny", "swift", "tidy", "tiny", "witty",
  "wobbly", "zany", "zesty", "zippy",
];

const ANIMALS = [
  "alpaca", "badger", "beaver", "bison", "camel", "cheetah", "cobra", "condor", "corgi", "coyote", "crane", "dingo",
  "dolphin", "donkey", "eagle", "falcon", "ferret", "gecko", "gibbon", "goose", "gopher", "heron", "hippo", "husky",
  "ibex", "iguana", "jackal", "koala", "lemur", "llama", "lynx", "magpie", "marmot", "meerkat", "moose", "narwhal",
  "newt", "ocelot", "otter", "owl", "panda", "parrot", "pelican", "penguin", "puffin", "quokka", "rabbit", "raccoon",
  "raven", "salmon", "seal", "shark", "sloth", "stoat", "tapir", "tiger", "toucan", "turtle", "walrus", "weasel",
  "wombat", "yak", "zebra", "vole",
];

const SESSION = /^https?:\/\/\S*?\/session_(\w+)$/;

/** 32-bit FNV-1a: a cheap, stable spread of the id's characters. */
function fnv1a(s: string) {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 0x01000193);
  return h >>> 0;
}

/** The nickname of a session URL's holder, or null when the assignee is not a session URL (a profile, `local`, unheld). */
export function sessionNickname(assignee: string): string | null {
  const id = SESSION.exec(assignee)?.[1];
  if (!id) return null;
  const h = fnv1a(id);
  return `${ADJECTIVES[h % ADJECTIVES.length]}-${ANIMALS[(h >>> 16) % ANIMALS.length]}`;
}
