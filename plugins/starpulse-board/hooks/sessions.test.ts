import type { On, RenderElement } from 'claude-code'
import { expect, test } from 'claude-code/testing'

// The suite runs on a host shared with other sessions, where each round trip to the engine can take a second.
const SLOW = 60_000
const OWN = 'session-own'
const NOW = 1_800_000_000_000
const MINUTE = 60_000
const PANE = 'starpulse-sessions'

// The registry every Claude Code session writes: this session in tmux claude-own, two interactive ones, a tmux session
// StarPulse started for TASK-7, and a background session with no tmux pane.
const REGISTRY: Record<string, object> = {
  '/home/me/.claude/sessions/100.json': { sessionId: OWN, pid: 100, name: 'trantor-d2', status: 'busy', kind: 'interactive', cwd: '/work', updatedAt: NOW - 2 * MINUTE },
  '/home/me/.claude/sessions/200.json': { sessionId: 'session-5d', pid: 200, name: 'trantor-5d', status: 'busy', kind: 'interactive', cwd: '/work/five', updatedAt: NOW - MINUTE },
  '/home/me/.claude/sessions/300.json': { sessionId: 'session-81', pid: 300, name: 'trantor-81', status: 'idle', kind: 'interactive', cwd: '/work/eighty', updatedAt: NOW - 12 * MINUTE },
  '/home/me/.claude/sessions/400.json': { sessionId: 'abcd1234-5678', pid: 400, name: 'Check the alert', status: 'idle', kind: 'bg', cwd: '/work/alert', updatedAt: NOW - 600 * MINUTE },
  '/home/me/.claude/sessions/500.json': { sessionId: 'session-t7', pid: 500, name: 'task-7 run', status: 'idle', kind: 'interactive', cwd: '/work/t7', updatedAt: NOW - 30 * MINUTE },
}

const PANES = '100 claude-own\n200 claude-5d\n300 claude-81\n500 task-7\n'

const BOARD = JSON.stringify({
  columns: [
    { state: 'in_progress', name: 'In Progress', tasks: [{ id: 'TASK-5020', title: 'Design', holder: OWN }, { id: 'TASK-7', title: 'Busy one', holder: 'session-t7' }] },
  ],
})

const ARCHIVED = { sessionId: 'old-77', name: 'trantor-77', cwd: '/work/old', task: 'TASK-9', archivedAt: NOW - 26 * 60 * MINUTE }

const PANE_PROPS = { title: 'Sessions', isFocused: false, bodyColumns: 52, placement: 'dock', scroll: { offset: 0, bodyRows: 30 }, view: {} } as const

declare const setTimeout: (fn: (value?: unknown) => void, ms: number) => unknown
const settle = async () => {
  for (let i = 0; i < 20; i++) await new Promise(r => setTimeout(r, 0))
}

const answer = (exitCode: number, stdout = '') => ({ value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })

type Host = {
  tmux: string[][]
  toasts: string[]
  store: Map<string, unknown>
  opened: string[]
  // Makes `tmux new-session` fail, as a server that is not running does.
  failNew?: boolean
}

const host = (on: On, seed: Partial<Host> = {}): Host => {
  const seen: Host = { tmux: [], toasts: [], opened: [], store: new Map(), ...seed }
  on('ui.render', ($, e) => h($.ui.resolve(e).Box, { key: 'engine' }) as RenderElement)
  on('session.id', () => ({ value: OWN }))
  on('session.root', () => ({ value: '/work' }))
  on('session.start', ($, e) => e)
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('clock.now', () => ({ value: NOW }))
  on('clock.every', () => ({ value: undefined }))
  on('clock.after', () => ({ value: undefined }))
  on('env.get', ($, e) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  on('store.get', ($, e) => ({ value: seen.store.get(e.key) }))
  on('store.set', ($, e) => {
    seen.store.set(e.key, JSON.parse(JSON.stringify(e.value)))
    return { value: undefined }
  })
  on('ui.toast', ($, e) => {
    seen.toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.open', ($, e) => {
    seen.opened.push(e.id)
    return { value: { isPlaced: true as const } }
  })
  on('ui.close', () => ({ value: undefined }))
  on('ui.focus', () => ({}))
  on('fs.list', () => ({
    value: Object.keys(REGISTRY).map(p => ({ name: p.split('/').at(-1)!, kind: 'file' as const, size: 1, mtimeMs: 0, isLink: false })),
  }))
  on('fs.read', ($, e) => ({ value: JSON.stringify(REGISTRY[e.path]) }))
  on('process.run', ($, e) => {
    if (e.argv[0] === 'tmux') {
      if (e.argv[1] === 'list-panes') return answer(0, PANES)
      seen.tmux.push([...e.argv])
      return answer(seen.failNew && e.argv[1] === 'new-session' ? 1 : 0)
    }
    return answer(0, BOARD)
  })
  on('process.spawn', async function* () {
    await new Promise<void>(() => {})
    return { value: { code: 0, signal: null } }
  })
  return seen
}

const start = async ($: any, surface: string) => {
  await $.session.start({ cwd: '/work', surface, isInteractive: true })
  await settle()
}

// Starting the session lists the others and opens the pane, which reads the Board; then a surface draws it.
const pane = async ($: any, surface: string, props: object = {}) =>
  $.ui.mount({ plugin: 'starpulse-board', surface, component: 'Pane', props: { ...PANE_PROPS, ...props }, requestId: PANE })

// The keys of the buttons under `prefix`, in the order they are drawn.
const keys = async (ui: any, prefix: string) =>
  (await ui.findAll({ type: 'Button' })).map((b: any) => String(b.key)).filter((k: string) => k.startsWith(prefix))

const label = async (ui: any, key: string) => String((await ui.find({ key }))?.props.label)

// The ring moving onto a Button: the engine resolves `key` to the `element` that ui.focus hooks read.
const focus = ($: any, key: string) => $.ui.focus({ requestId: PANE, key, element: key })

// The tmux session names a test did not choose.
const AUTO = /^claude-\d{6}$/

for (const surface of ['terminal', 'desktop'] as const) {
  test(`the pane groups sessions into Working and Idle, this one first with its marker and task (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    host(on)
    await start($, surface)
    const ui = await pane($, surface)

    expect(await keys(ui, 'fold:')).toEqual(['fold:working', 'fold:idle'])
    expect(await keys(ui, 'session:')).toEqual([`session:${OWN}`, 'session:session-5d', 'session:session-81', 'session:session-t7', 'session:abcd1234-5678'])
    expect(await label(ui, `session:${OWN}`)).toBe('trantor-d2, you, TASK-5020, working, 2m')
    expect(await label(ui, 'session:session-t7')).toBe('task-7 run, TASK-7, idle, 30m')
    expect(await label(ui, 'session:abcd1234-5678')).toBe('Check the alert, background, idle, 10h')
    await ui.unmount()
  })

  test(`the chips count every session by status and the filter row names its keys (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    host(on, { store: new Map([['archived', [ARCHIVED]]]) })
    await start($, surface)
    const ui = await pane($, surface)

    expect(await label(ui, 'chip:working')).toBe('working 2')
    expect(await label(ui, 'chip:idle')).toBe('idle 3')
    expect(await label(ui, 'chip:bg')).toBe('bg 1')
    expect(await label(ui, 'chip:archived')).toBe('archived 1')
    expect((await ui.find({ key: 'new' }))?.props.hotkey).toBe('n')
    expect((await ui.find({ key: 'focus-filter' }))?.props.hotkey).toBe('f')
    expect((await ui.find({ key: 'archive-focused' }))?.props.hotkey).toBe('a')
    expect(await ui.find({ key: 'filter' })).toBeDefined()
    await ui.unmount()
  })

  test(`n starts a new tmux session running claude in the workspace and switches to it (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    const h = host(on)
    await start($, surface)
    const ui = await pane($, surface)

    await ui.press({ key: 'new' })

    const [created, switched] = h.tmux
    expect(created?.slice(0, 5)).toEqual(['tmux', 'new-session', '-d', '-s', created?.[4]])
    expect(created?.[4]).toMatch(AUTO)
    expect(created?.slice(5)).toEqual(['-c', '/work', 'claude'])
    expect(switched).toEqual(['tmux', 'switch-client', '-t', created?.[4]])
    await ui.unmount()
  })

  test(`a new session that tmux cannot start toasts and does not switch (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    const h = host(on, { failNew: true })
    await start($, surface)
    const ui = await pane($, surface)

    await ui.press({ key: 'new' })

    expect(h.tmux.map(argv => argv[1])).toEqual(['new-session'])
    expect(h.toasts).toEqual(['Cannot start a tmux session: is tmux installed?'])
    await ui.unmount()
  })

  test(`the filter matches a session's name, tmux session or task (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    host(on)
    await start($, surface)
    const ui = await pane($, surface)

    await ui.input({ key: 'filter', text: 'TRANTOR', kind: 'change' })
    expect(await keys(ui, 'session:')).toEqual([`session:${OWN}`, 'session:session-5d', 'session:session-81'])

    await ui.input({ key: 'filter', text: 'claude-81', kind: 'change' })
    expect(await keys(ui, 'session:')).toEqual(['session:session-81'])

    await ui.input({ key: 'filter', text: 'task-7', kind: 'change' })
    expect(await keys(ui, 'session:')).toEqual(['session:session-t7'])

    await ui.input({ key: 'filter', text: 'nothing like it', kind: 'change' })
    expect(await keys(ui, 'session:')).toEqual([])
    expect(await ui.find({ text: 'No session matches “nothing like it”' })).toBeDefined()
    await ui.unmount()
  })

  test(`status chips toggle and combine as OR, and with the text as AND (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    host(on)
    await start($, surface)
    const ui = await pane($, surface)

    await ui.press({ key: 'chip:idle' })
    expect(await keys(ui, 'session:')).toEqual(['session:session-81', 'session:session-t7', 'session:abcd1234-5678'])

    await ui.press({ key: 'chip:working' })
    expect(await keys(ui, 'session:')).toHaveLength(5)

    await ui.press({ key: 'chip:working' })
    await ui.press({ key: 'chip:idle' })
    await ui.press({ key: 'chip:bg' })
    expect(await keys(ui, 'session:')).toEqual(['session:abcd1234-5678'])

    await ui.press({ key: 'chip:bg' })
    await ui.press({ key: 'chip:idle' })
    await ui.input({ key: 'filter', text: 'trantor', kind: 'change' })
    expect(await keys(ui, 'session:')).toEqual(['session:session-81'])
    await ui.unmount()
  })

  test(`a group header folds and unfolds its rows (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    host(on)
    await start($, surface)
    const ui = await pane($, surface)

    await ui.press({ key: 'fold:idle' })
    expect(await keys(ui, 'session:')).toEqual([`session:${OWN}`, 'session:session-5d'])
    await ui.press({ key: 'fold:idle' })
    expect(await keys(ui, 'session:')).toHaveLength(5)
    await ui.unmount()
  })

  test(`archiving another session kills its tmux session, hides it and keeps it in $.store (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    const h = host(on)
    await start($, surface)
    const ui = await pane($, surface)

    await ui.press({ key: 'archive:session-81' })

    expect(h.tmux).toEqual([['tmux', 'kill-session', '-t', 'claude-81']])
    expect(await ui.find({ key: 'session:session-81' })).toBeUndefined()
    expect(await label(ui, 'chip:archived')).toBe('archived 1')
    expect(h.store.get('archived')).toEqual([{ sessionId: 'session-81', name: 'trantor-81', cwd: '/work/eighty', task: '', archivedAt: NOW }])
    await ui.unmount()
  })

  test(`archiving the current session opens a fresh tmux session and switches to it before killing this one (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    const h = host(on)
    await start($, surface)
    const ui = await pane($, surface)

    await ui.press({ key: `archive:${OWN}` })

    const [created, switched, killed] = h.tmux
    expect(created?.[1]).toBe('new-session')
    expect(created?.[4]).toMatch(AUTO)
    expect(created?.slice(5)).toEqual(['-c', '/work', 'claude'])
    expect(switched).toEqual(['tmux', 'switch-client', '-t', created?.[4]])
    expect(killed).toEqual(['tmux', 'kill-session', '-t', 'claude-own'])
    expect(h.tmux).toHaveLength(3)
    expect(h.store.get('archived')).toEqual([{ sessionId: OWN, name: 'trantor-d2', cwd: '/work', task: 'TASK-5020', archivedAt: NOW }])
    await ui.unmount()
  })

  test(`archiving the current session keeps it when the fresh tmux session cannot start (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    const h = host(on, { failNew: true })
    await start($, surface)
    const ui = await pane($, surface)

    await ui.press({ key: `archive:${OWN}` })

    expect(h.tmux.map(argv => argv[1])).toEqual(['new-session'])
    expect(h.store.get('archived')).toBeUndefined()
    expect(await ui.find({ key: `session:${OWN}` })).toBeDefined()
    expect(h.toasts).toEqual(['Not archived: no fresh tmux session to switch to first'])
    await ui.unmount()
  })

  test(`archived sessions load from $.store, stay folded until chosen, and resume in a new tmux session (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    const h = host(on, { store: new Map([['archived', [ARCHIVED]]]) })
    await start($, surface)
    const ui = await pane($, surface)

    expect(await keys(ui, 'fold:')).toEqual(['fold:working', 'fold:idle', 'fold:archived'])
    expect(await keys(ui, 'session:')).not.toContain('session:old-77')

    await ui.press({ key: 'fold:archived' })
    expect(await label(ui, 'session:old-77')).toBe('trantor-77, TASK-9, archived, 1d')

    await ui.press({ key: 'resume:old-77' })

    const [created, switched] = h.tmux
    expect(created?.[4]).toMatch(AUTO)
    expect(created?.slice(5)).toEqual(['-c', '/work/old', 'claude', '--resume', 'old-77'])
    expect(switched).toEqual(['tmux', 'switch-client', '-t', created?.[4]])
    expect(h.store.get('archived')).toEqual([])
    expect(await ui.find({ key: 'session:old-77' })).toBeUndefined()
    await ui.unmount()
  })

  test(`the archived chip unfolds Archived and shows only archived rows (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    host(on, { store: new Map([['archived', [ARCHIVED]]]) })
    await start($, surface)
    const ui = await pane($, surface)

    await ui.press({ key: 'chip:archived' })

    expect(await keys(ui, 'session:')).toEqual(['session:old-77'])
    await ui.unmount()
  })

  test(`an archived session still in the registry stays out of the live groups (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    host(on, { store: new Map([['archived', [{ ...ARCHIVED, sessionId: 'session-81' }]]]) })
    await start($, surface)
    const ui = await pane($, surface)

    expect(await keys(ui, 'session:')).not.toContain('session:session-81')
    expect(await label(ui, 'chip:idle')).toBe('idle 2')
    await ui.unmount()
  })

  test(`pressing a row switches to its tmux session, and this session's row only says so (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    const h = host(on)
    await start($, surface)
    const ui = await pane($, surface)

    await ui.press({ key: 'session:session-5d' })
    await ui.press({ key: `session:${OWN}` })

    expect(h.tmux).toEqual([['tmux', 'switch-client', '-t', 'claude-5d']])
    expect(h.toasts).toEqual(['This is the session you are in'])
    await ui.unmount()
  })

  test(`a on the focused row archives it; on an archived row it resumes it (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    const h = host(on, { store: new Map([['archived', [ARCHIVED]]]) })
    await start($, surface)
    const ui = await pane($, surface)

    await focus($, 'session:session-81')
    await ui.press({ key: 'archive-focused' })
    expect(h.tmux).toEqual([['tmux', 'kill-session', '-t', 'claude-81']])

    await ui.press({ key: 'fold:archived' })
    await focus($, 'resume:old-77')
    await ui.press({ key: 'archive-focused' })
    expect(h.tmux.at(-1)).toEqual(['tmux', 'switch-client', '-t', h.tmux.at(-2)?.[4]])
    await ui.unmount()
  })

  test(`a on a pane with nothing focused toasts instead of archiving (${surface})`, { timeoutMs: SLOW }, async ($, on) => {
    const h = host(on)
    await start($, surface)
    const ui = await pane($, surface)

    await ui.press({ key: 'archive-focused' })

    expect(h.tmux).toEqual([])
    expect(h.toasts).toEqual(['Focus a session with ↑↓ first'])
    await ui.unmount()
  })
}

test('a narrow dock cuts the name before the task chip and the age', { timeoutMs: SLOW }, async ($, on) => {
  host(on)
  await start($, 'terminal')
  const ui = await pane($, 'terminal', { bodyColumns: 34 })

  const row = (await ui.find({ key: `session:${OWN}` }))?.text ?? ''
  expect(row).toContain('…')
  expect(row).toContain('TASK-5020')
  expect(row).toContain('you')
  expect([...row].length).toBeLessThanOrEqual(34)
  await ui.unmount()
})

for (const [mode, working, archive, resume] of [
  ['nerd', '', '', ''],
  ['plain', '●', '×', '▶'],
] as const) {
  test(`glyphs=${mode}: rows and the archive icon draw the ${mode} characters`, { options: { glyphs: mode }, timeoutMs: SLOW }, async ($, on) => {
    host(on, { store: new Map([['archived', [ARCHIVED]]]) })
    await start($, 'terminal')
    const ui = await pane($, 'terminal')
    await ui.press({ key: 'fold:archived' })

    expect(await ui.find({ key: `archive:${OWN}`, text: archive })).toBeDefined()
    expect(await ui.find({ key: 'resume:old-77', text: resume })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: new RegExp(working) })).toBeDefined()
    await ui.unmount()
  })
}

test('the pane draws no fill: its root is black and every Button is plain', { timeoutMs: SLOW }, async ($, on) => {
  host(on)
  await start($, 'terminal')
  const ui = await pane($, 'terminal')

  const buttons = await ui.findAll({ type: 'Button' })
  expect(buttons.length).toBeGreaterThan(5)
  for (const b of buttons) expect(b.props.plain, String(b.key)).toBe(true)
  expect((await ui.drawn()).props?.backgroundColor).toBe('#000000')
  await ui.unmount()
})
