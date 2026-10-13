import type { Checks, HeldTask } from '../types'

// StarPulse's :root tokens (starpulse/web/src/style.css). An Svg is drawn isolated, so it spells them out.
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
  released: '#5eead4',
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
  bg: ['\uf186', '◐'],
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

const FONT = "Inter,system-ui,-apple-system,'Segoe UI',sans-serif"
const MONO = "'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace"

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

/** The sentence a screen reader gets for the row. */
export const alt = (t: HeldTask) => {
  const p = progress(t)
  const parts = [`${t.id}: ${laneOf(t)[0]}`]
  if (p) {
    parts.push(p.k === null ? count(p.n) : `${p.k} of ${p.n} criteria`)
  }
  if (t.pull) {
    parts.push(`PR #${t.pull.number} ${CHECKS[t.pull.checks].phrase}`)
  }

  return parts.join(', ')
}

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

const xml = (t = '') => t.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] as string)

// The module has no canvas to measure with, so widths come from per-glyph advances in em, a little generous.
const advance = (ch: string) => {
  if ('iljtfI.,;:!|\'`'.includes(ch)) {
    return 0.3
  }
  if ('mwMW@%'.includes(ch)) {
    return 0.85
  }
  if (ch === ' ') {
    return 0.28
  }
  if (/[A-Z0-9]/.test(ch)) {
    return 0.64
  }

  return 0.56
}

const width = (text: string, size: number, isMono = false, weight = 400) => {
  const em = isMono ? text.length * 0.6 : [...text].reduce((sum, ch) => sum + advance(ch), 0)

  return em * size * (weight >= 500 ? 1.04 : 1)
}

const fit = (text: string, size: number, room: number, isMono = false, weight = 400) => {
  if (room < 30) {
    return ''
  }
  if (width(text, size, isMono, weight) <= room) {
    return text
  }
  let out = ''
  for (const ch of text) {
    if (width(`${out}${ch}…`, size, isMono, weight) > room) {
      break
    }
    out += ch
  }

  return `${out}…`
}

// At most two lines; the second is cut with an ellipsis when the text runs on.
const wrap = (text: string, size: number, room: number, weight = 400) => {
  const lines: string[] = []
  let line = ''
  for (const word of text.split(' ')) {
    const next = line ? `${line} ${word}` : word
    if (line && width(next, size, false, weight) > room) {
      lines.push(line)
      line = word
    } else {
      line = next
    }
  }
  lines.push(line)

  return lines.length > 2 ? [lines[0], fit(lines.slice(1).join(' '), size, room, false, weight)] : lines
}

const noise = (a: number, b: number) => {
  const x = Math.sin(a * 127.1 + b * 311.7) * 43758.5453

  return x - Math.floor(x)
}

// Motion stops under the system's reduced-motion setting; a lane that is not live, and a pass or fail check, never pulse.
const style = (isLive: boolean) =>
  '<style>' +
  '.t0,.t1,.t2,.t3{animation:tw 2.4s ease-in-out infinite}.t1{animation-duration:2.9s;animation-delay:-.7s}.t2{animation-duration:2s;animation-delay:-1.3s}.t3{animation-duration:3.3s;animation-delay:-.4s}' +
  '@keyframes tw{0%,100%{opacity:1}50%{opacity:.35}}.live{animation:p 1.6s ease-in-out infinite}@keyframes p{50%{opacity:.3}}' +
  '@media (prefers-reduced-motion: reduce){.t0,.t1,.t2,.t3,.live{animation:none}}' +
  `${isLive ? '' : '.t0,.t1,.t2,.t3{animation:none}'}</style>`

const card = (w: number, h: number) =>
  `<rect x=".5" y=".5" width="${w - 1}" height="${h - 1}" rx="7" fill="${SP.surface}" stroke="${SP.slate}" stroke-opacity=".13"/>`

const pill = (x: number, y: number, w: number, color: string, label: string, size = 11) =>
  `<rect x="${x}" y="${y}" width="${w}" height="18" rx="9" fill="${color}" fill-opacity=".14"/>` +
  `<circle cx="${x + 11}" cy="${y + 9}" r="3" fill="${color}"/>` +
  `<text x="${x + 19}" y="${y + 12.8}" font-family="${FONT}" font-size="${size}" font-weight="500" fill="${color}">${xml(label)}</text>`

const pillWidth = (label: string) => Math.ceil(width(label, 11, false, 500)) + 26

export const ROW_HEIGHT = 30

/** The band's row as one StarPulse card: lane dot, ID, title or reason, AC bar, lane pill, PR and its checks. */
export const rowSvg = (t: HeldTask, W: number) => {
  const PAD = 10
  const BAR_H = 12
  const CELL = 3
  const H = ROW_HEIGHT
  const mid = H / 2
  const [laneName, color] = laneOf(t)
  const p = progress(t)
  const isLive = t.lane === 'in_progress'
  const pr = t.pull ? `#${t.pull.number}` : ''
  const prW = t.pull ? Math.ceil(width(pr, 11.5, true)) + 16 : 0
  const laneW = pillWidth(laneName)
  const idW = Math.ceil(width(t.id, 11.5, true))
  const showPr = t.pull !== null && W >= 300
  const sub = subline(t)
  const left = PAD + 14 + idW + 10
  const laneX = W - PAD - laneW - (showPr ? prW + 8 : 0)
  const prX = laneX + laneW + 8
  const text = p && p.k === null ? ratio(p) : ''
  let barW = p?.k !== null && p ? Math.max(70, Math.min(220, W * 0.26)) : Math.ceil(width(text, 11))
  let titleMax = laneX - 10 - barW - 10 - left
  // Too narrow for a readable title: drop it and give the bar the room.
  if (titleMax < 80) {
    titleMax = 0
    if (p && p.k !== null) {
      barW = Math.max(40, laneX - 10 - 10 - left)
    }
  }
  const barX = laneX - 10 - barW
  const k = p?.k ?? 0
  const fillW = p ? Math.round((barW * k) / p.n) : 0
  const cols = Math.floor(fillW / CELL)
  const rows = Math.floor(BAR_H / CELL)
  const dots: string[] = []
  const ticks: string[] = []
  for (let c = 0; c < cols; c++) {
    const density = 0.4 + 0.55 * Math.pow(c / Math.max(1, cols), 1.2)
    for (let r = 0; r < rows; r++) {
      if (noise(c, r) < density) {
        dots.push(`<rect class="t${Math.floor(noise(r, c) * 4)}" x="${c * CELL + 1}" y="${r * CELL + 1}" width="2" height="2"/>`)
      }
    }
  }
  for (let i = 1; p && i < p.n; i++) {
    const x = Math.round((barW * i) / p.n)
    if (x > fillW + 3) {
      ticks.push(`<rect x="${x}" y="${BAR_H / 2 - 3}" width="1.5" height="6" rx=".75"/>`)
    }
  }
  const label = `${k}/${p?.n ?? 0}`
  const labelW = Math.round(14 + label.length * 6.2)
  const labelX = Math.max(0, Math.min(barW - labelW, fillW - labelW))
  const meter =
    p && p.k !== null
      ? `<g transform="translate(${barX},${(H - BAR_H) / 2})">` +
        `<rect width="${barW}" height="${BAR_H}" rx="${BAR_H / 2}" fill="${SP.slate}" fill-opacity=".12"/>` +
        `<g clip-path="url(#c)"><g fill="${color}">${dots.join('')}</g><g fill="${SP.track}">${ticks.join('')}</g></g>` +
        `<rect x="${labelX}" width="${labelW}" height="${BAR_H}" rx="${BAR_H / 2}" fill="${k ? color : SP.track}"/>` +
        `<text x="${labelX + labelW / 2}" y="${BAR_H / 2 + 3.6}" text-anchor="middle" font-family="${FONT}" font-size="10" font-weight="600" font-variant-numeric="tabular-nums" fill="${k ? SP.ink0 : SP.slate}">${label}</text></g>`
      : p
        ? `<text x="${barX}" y="${mid + 4}" font-family="${FONT}" font-size="11" fill="${SP.muted}">${xml(text)}</text>`
        : ''
  const checks = t.pull ? CHECKS[t.pull.checks] : null
  const pulse = (on: boolean) => (on ? ' class="live"' : '')

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${style(isLive)}` +
    `<defs><clipPath id="c"><rect width="${barW}" height="${BAR_H}" rx="${BAR_H / 2}"/></clipPath><clipPath id="tc"><rect x="${left}" width="${titleMax}" height="${H}"/></clipPath><filter id="g" x="-2" y="-2" width="5" height="5"><feGaussianBlur stdDeviation="2"/></filter></defs>` +
    card(W, H) +
    `<circle cx="${PAD + 4}" cy="${mid}" r="4" fill="${color}" filter="url(#g)" opacity=".6"/>` +
    `<circle${pulse(isLive)} cx="${PAD + 4}" cy="${mid}" r="3.5" fill="${color}"/>` +
    `<text x="${PAD + 14}" y="${mid + 4}" font-family="${MONO}" font-size="11.5" fill="${SP.slate}">${xml(t.id)}</text>` +
    (titleMax ? `<text clip-path="url(#tc)" x="${left}" y="${mid + 4.5}" font-family="${FONT}" font-size="13" fill="${sub.color}">${xml(fit(sub.text, 13, titleMax))}</text>` : '') +
    meter +
    pill(laneX, mid - 9, laneW, color, laneName) +
    (showPr && checks
      ? `<circle${pulse(t.pull?.checks === 'pending')} cx="${prX + 4}" cy="${mid}" r="3.5" fill="${checks.color}"><title>${checks.phrase}</title></circle>` +
        `<text x="${prX + 12}" y="${mid + 4}" font-family="${MONO}" font-size="11.5" fill="${SP.muted}">${pr}</text>`
      : '') +
    '</svg>'
  )
}

/** The pane as one StarPulse panel: ID, title, lane and holder, reason or waits, criteria with ticks, PR and checks. */
export const paneSvg = (t: HeldTask, W: number) => {
  const P = 14
  const inner = W - 2 * P
  const [laneName, color] = laneOf(t)
  const p = progress(t)
  const parts: string[] = []
  let y = P
  parts.push(`<text x="${P}" y="${(y += 12)}" font-family="${MONO}" font-size="11.5" fill="${SP.slate}">${xml(t.id)}</text>`)
  for (const l of wrap(t.title, 14, inner, 500)) {
    parts.push(`<text x="${P}" y="${(y += 20)}" font-family="${FONT}" font-size="14" font-weight="500" fill="${SP.ink}">${xml(l)}</text>`)
  }
  y += 10
  const holder = /^[0-9a-f]{8}-/.test(t.holder) ? t.holder.slice(0, 8) : t.holder
  parts.push(pill(P, y, pillWidth(laneName), color, laneName))
  if (holder) {
    parts.push(`<text x="${P + pillWidth(laneName) + 8}" y="${y + 13}" font-family="${FONT}" font-size="12" fill="${SP.muted}">held by ${xml(holder)}</text>`)
  }
  y += 24
  if (t.reason) {
    for (const l of wrap(t.reason, 12.5, inner)) {
      parts.push(`<text x="${P}" y="${(y += 15)}" font-family="${FONT}" font-size="12.5" fill="${t.lane === 'needs_attention' ? SP.failText : SP.ink}">${xml(l)}</text>`)
    }
    y += 8
  }
  if (t.lane === 'waiting' && t.waitingOn.length) {
    parts.push(
      `<text x="${P}" y="${(y += 14)}" font-family="${FONT}" font-size="12.5" fill="${SP.muted}">Waiting on <tspan font-family="${MONO}" fill="${SP.slate}">${xml(t.waitingOn.join('  '))}</tspan></text>`,
    )
    y += 8
  }
  const rule = (at: number) => `<rect x="${P}" y="${at}" width="${inner}" height="1" fill="${SP.slate}" fill-opacity=".10"/>`
  if (p) {
    parts.push(rule(y + 2))
    y += 12
    parts.push(
      `<text x="${P}" y="${(y += 13)}" font-family="${FONT}" font-size="11" font-weight="500" letter-spacing="2.2" fill="${SP.slate}">ACCEPTANCE CRITERIA <tspan letter-spacing="0" fill="${SP.muted}" font-variant-numeric="tabular-nums">${p.k === null ? p.n : `${p.k}/${p.n}`}</tspan></text>`,
    )
    y += 6
    for (const c of t.criteria ?? []) {
      const lines = wrap(c.text, 13, inner - 24)
      const cy = y + 12
      parts.push(
        c.checked === true
          ? `<path d="M${P + 2} ${cy}l4 4 7-8" fill="none" stroke="${SP.okHi}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>`
          : c.checked === false
            ? `<rect x="${P + 1.5}" y="${cy - 6}" width="12" height="12" rx="3" fill="none" stroke="${SP.slate}" stroke-opacity=".45" stroke-width="1.3"/>`
            : `<circle cx="${P + 7}" cy="${cy}" r="2" fill="${SP.slate}" fill-opacity=".6"/>`,
      )
      lines.forEach((l, j) =>
        parts.push(`<text x="${P + 22}" y="${cy + 4.5 + j * 17}" font-family="${FONT}" font-size="13" fill="${c.checked ? SP.muted : SP.ink}">${xml(l)}</text>`),
      )
      y += 8 + lines.length * 17
    }
  }
  if (t.pull) {
    const checks = CHECKS[t.pull.checks]
    const ref = `${t.pull.repo}#${t.pull.number}`
    parts.push(rule(y + 6))
    y += 14
    parts.push(
      `<circle${t.pull.checks === 'pending' ? ' class="live"' : ''} cx="${P + 4}" cy="${y + 8}" r="3.5" fill="${checks.color}"/>` +
        `<text x="${P + 14}" y="${y + 12}" font-family="${MONO}" font-size="12" fill="${SP.agent}">${xml(ref)}</text>` +
        `<text x="${P + 22 + width(ref, 12, true)}" y="${y + 12}" font-family="${FONT}" font-size="12.5" fill="${SP.muted}">${checks.phrase}</text>`,
    )
    y += 22
  }
  const H = Math.ceil(y + P - 4)

  return {
    height: H,
    source: `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${style(false)}${card(W, H)}${parts.join('')}</svg>`,
  }
}
