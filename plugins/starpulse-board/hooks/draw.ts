import type { Checks, HeldTask } from '../types'

// StarPulse's :root tokens (starpulse/web/src/style.css).
export const SP = {
  black: '#000000',
  ink: '#dbe4f3',
  slate: '#94a3b8',
  muted: '#6b7a93',
  track: '#334155',
  faint: '#475569',
  surface: '#0c1322',
  ok: '#34d399',
  okHi: '#6ee7b7',
  run: '#fbbf24',
  fail: '#fb7185',
  failText: '#fda4af',
  agent: '#a78bfa',
  ready: '#60a5fa',
  ink0: '#05070d',
}
// Every icon the terminal draws: its Nerd Font v3 codepoint, then the plain Unicode character for a terminal without
// the font. A terminal cannot report its font, so the `glyphs` option picks the column.
const GLYPHS = {
  down: ['\uf078', '▾'],
  right: ['\uf054', '▸'],
  working: ['\uf111', '●'],
  idle: ['\uf10c', '○'],
  ready: ['\uf01c', '◇'],
  in_progress: ['\uf04b', '▶'],
  review: ['\uf06e', '◉'],
  needs_attention: ['\uf071', '!'],
  waiting: ['\uf252', '…'],
  done: ['\uf00c', '✓'],
  pass: ['\uf058', '✓'],
  pending: ['\uf192', '●'],
  fail: ['\uf057', '✗'],
  none: ['\uf1db', '○'],
  pr: ['\uf407', '#'],
  go: ['\uf08e', '↗'],
  start: ['\uf04b', '▶'],
  move: ['\uf061', '→'],
  refresh: ['\uf021', '↻'],
  board: ['\uf0db', '▦'],
  new: ['\uf067', '+'],
  filter: ['\uf002', '/'],
  archived: ['\uf187', '▪'],
  archive: ['\uf187', '×'],
  you: ['\uf007', '•'],
} as const

export type Glyph = keyof typeof GLYPHS
export type Glyphs = (name: Glyph) => string

/** The icon lookup for the `glyphs` option: anything but `plain` draws Nerd Font. */
export const glyphs = (mode: unknown): Glyphs => {
  const column = mode === 'plain' ? 1 : 0

  return name => GLYPHS[name][column]
}

/** A lane's icon: the glyph of its own name, `none` for a lane the map lacks. */
export const laneIcon = (g: Glyphs, lane: string) => g(lane in GLYPHS ? (lane as Glyph) : 'none')

// The lane pill's name and colour, by the Board machine's state id.
export const LANES: Record<string, [string, string]> = {
  ready: ['Ready', SP.ready],
  in_progress: ['In Progress', SP.run],
  review: ['Review', SP.agent],
  needs_attention: ['Needs attention', SP.fail],
  waiting: ['Waiting', SP.slate],
  done: ['Done', SP.ok],
}

// What a pull request's checks say and their colour; the terminal's icon is the glyph named for the check.
export const CHECKS: Record<Checks, { phrase: string; color: string }> = {
  pass: { phrase: 'checks pass', color: SP.ok },
  pending: { phrase: 'checks running', color: SP.run },
  fail: { phrase: 'checks failing', color: SP.fail },
  none: { phrase: 'no checks', color: SP.slate },
}

export const laneOf = (t: HeldTask): [string, string] => LANES[t.lane] ?? [t.column, SP.slate]

const count = (n: number) => `${n} ${n === 1 ? 'criterion' : 'criteria'}`

// k of n criteria checked; k is null when the server serves no checked state, so only the count is known.
export type Progress = { n: number; k: number | null }

export const progress = (t: HeldTask): Progress | null => {
  if (!t.criteria?.length) {
    return null
  }
  const n = t.criteria.length
  const ticks = t.criteria.map(c => c.checked)

  return { n, k: ticks.every(c => typeof c === 'boolean') ? ticks.filter(Boolean).length : null }
}

/** `2/4` when the checked state is served, else `4 criteria`. */
export const ratio = (p: Progress) => (p.k === null ? count(p.n) : `${p.k}/${p.n}`)

/** What the row says beside the ID: the title, or the reason a parked task gives, or what a waiting task waits on. */
export const subline = (t: HeldTask): { text: string; color: string } => {
  if (t.reason) {
    return { text: t.reason, color: t.lane === 'needs_attention' ? SP.failText : SP.ink }
  }
  if (t.lane === 'waiting' && t.waitingOn.length) {
    return { text: `waiting on ${t.waitingOn.join(', ')}`, color: SP.slate }
  }

  return { text: t.title, color: SP.ink }
}

/** An eighth-block bar of `cells` cells, k of n filled, as its filled part and its empty track. */
export const termBar = (k: number, n: number, cells = 12): [fill: string, track: string] => {
  const eighths = Math.round((cells * 8 * k) / Math.max(1, n))
  const full = '█'.repeat(Math.floor(eighths / 8)) + (eighths % 8 ? '▏▎▍▌▋▊▉'[(eighths % 8) - 1] : '')

  return [full, '░'.repeat(cells - [...full].length)]
}
