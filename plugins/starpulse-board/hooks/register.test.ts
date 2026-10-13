import type { On, RenderElement } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

const PULL = 'https://github.com/trantor-org/starpulse/pull'
const CRITERIA = [true, true, false, false].map((checked, i) => ({ text: `Criterion ${i + 1}`, checked }))

// A task as `starpulse board --holder` prints it.
const task = (fields: Record<string, unknown>) => ({
  holder: 'session-1',
  criteria: CRITERIA,
  pause_reason: '',
  waiting_on: [],
  prs: [{ url: `${PULL}/392`, number: 392, checks: 'pending' }],
  ...fields,
})

const board = (columns: [string, string, unknown[]][]) =>
  JSON.stringify({ columns: columns.map(([state, name, tasks]) => ({ state, name, tasks })) })

const BOARD = board([
  ['in_progress', 'In Progress', [task({ id: 'PROJ-1', title: 'Add the verbs' })]],
  [
    'review',
    'Review',
    [task({ id: 'PROJ-2', title: 'Rotate the secret', criteria: CRITERIA.map(c => ({ ...c, checked: true })), prs: [{ url: `${PULL}/388`, checks: 'pass' }] })],
  ],
])

const SESSION = 'session-1'

const PROPS = {
  hasSurvey: false,
  isWorking: false,
  maxRows: 4,
  bodyColumns: 120,
  scroll: { offset: 0, bodyRows: 20 },
  view: {},
}

const PANE_PROPS = {
  title: 'Task',
  isFocused: false,
  bodyColumns: 80,
  placement: 'inline',
  scroll: { offset: 0, bodyRows: 20 },
  view: {},
} as const

const RUN = { command: 'board', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as const

// The test runner's timer; the plugin's own lib (es2023, no DOM) declares none.
declare const setTimeout: (fn: (value?: unknown) => void, ms: number) => unknown

// Lets a refresh the engine did not await finish.
const settle = async () => {
  for (let i = 0; i < 20; i++) await new Promise(r => setTimeout(r, 0))
}

const answer = (exitCode: number, stdout: string) => ({
  value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})

type Calls = { run?: (e: { argv: readonly string[] }) => ReturnType<typeof answer>; open?: (id: string) => void; close?: (id: string) => void }

// Serves `stdout` as the board and stands in for the engine's own drawing and panes.
const serve = (on: any, stdout: string, calls: Calls = {}) => {
  on('ui.render', ($: any, e: any) => h($.ui.resolve(e).Box, { key: 'engine' }) as RenderElement)
  on('session.id', () => ({ value: SESSION }))
  on('process.run', (_$: any, e: any) => calls.run?.(e) ?? answer(0, stdout))
  on('ui.open', (_$: any, e: any) => {
    calls.open?.(e.id)
    return { value: { isPlaced: true } }
  })
  on('ui.close', (_$: any, e: any) => {
    calls.close?.(e.id)
    return { value: undefined }
  })
}

const band = ($: any, surface: string, props: object = PROPS) =>
  $.ui.mount({ plugin: 'starpulse-board', surface, component: 'AbovePrompt', props })

const pane = ($: any, surface: string) =>
  $.ui.mount({ plugin: 'starpulse-board', surface, component: 'Pane', props: PANE_PROPS, requestId: 'starpulse-board' })

// The colour of the dot a terminal row draws for its task's PR checks.
const checkColor = async (ui: any, id: string) => ((await ui.find({ key: `checks-${id}` }))?.children[0] as { props: { color: string } } | undefined)?.props.color

// The Svg a desktop band or pane draws.
const drawn = async (ui: any) => (await ui.find({ type: 'Svg' }))?.props as { source: string; alt: string } | undefined

for (const surface of ['terminal', 'desktop'] as const) {
  test(`/board lists the tasks this session holds (${surface})`, async ($, on) => {
    let argv: readonly string[] = []
    serve(on, BOARD, {
      run: e => {
        argv = e.argv
        return answer(0, BOARD)
      },
    })

    const { text } = await $.command.run(RUN)

    expect(argv).toEqual(['starpulse', 'board', '--holder', SESSION])
    expect(text).toBe('PROJ-1 [In Progress] Add the verbs\nPROJ-2 [Review] Rotate the secret')
  })

  test(`an older starpulse on PATH falls back to ~/.local/bin (${surface})`, async ($, on) => {
    const argv0: string[] = []
    serve(on, BOARD, {
      run: e => {
        if (e.argv[0] === 'tmux') return answer(1, '')
        argv0.push(e.argv[0] ?? '')
        return e.argv[0] === 'starpulse' ? answer(2, '') : answer(0, BOARD)
      },
    })
    on('env.get', () => ({ value: '/home/me' }))

    const { text } = await $.command.run(RUN)

    expect(argv0).toEqual(['starpulse', '/home/me/.local/bin/starpulse'])
    expect(text).toBe('PROJ-1 [In Progress] Add the verbs\nPROJ-2 [Review] Rotate the secret')
  })

  test(`no starpulse on PATH falls back to ~/.local/bin and draws the band (${surface})`, async ($, on) => {
    const argv0: string[] = []
    serve(on, BOARD, {
      run: e => {
        if (e.argv[0] === 'tmux') return answer(1, '')
        argv0.push(e.argv[0] ?? '')
        if (e.argv[0] === 'starpulse') {
          throw new Error('ENOENT: Executable not found in $PATH: "starpulse"')
        }
        return answer(0, BOARD)
      },
    })
    on('env.get', () => ({ value: '/home/me' }))

    const { text } = await $.command.run(RUN)
    const ui = await band($, surface)

    expect(argv0).toEqual(['starpulse', '/home/me/.local/bin/starpulse'])
    expect(text).toBe('PROJ-1 [In Progress] Add the verbs\nPROJ-2 [Review] Rotate the secret')
    expect(await ui.find({ key: 'hide' })).toBeDefined()
  })

  test(`✕ takes the band down to Show task until /board (${surface})`, async ($, on) => {
    serve(on, BOARD)

    await $.command.run(RUN)
    const ui = await band($, surface)
    await ui.press({ key: 'hide' })

    expect(await ui.find({ key: 'hide' })).toBeUndefined()
    expect(await ui.find({ key: 'show' })).toBeDefined()
    await ui.press({ key: 'show' })
    expect(await ui.find({ key: 'hide' })).toBeDefined()
  })

  for (const [why, exitCode, stdout] of [
    ['no server', 3, ''],
    ['no held task', 0, board([['ready', 'Ready', []]])],
  ] as const) {
    test(`no band with ${why} (${surface})`, async ($, on) => {
      serve(on, '', { run: () => answer(exitCode, stdout) })

      const { text } = await $.command.run(RUN)
      const ui = await band($, surface)

      expect(text).toBe(exitCode ? '`starpulse board` failed: is the StarPulse server running?' : 'This session holds no tasks.')
      expect(await ui.find({ key: 'hide' })).toBeUndefined()
      expect(await ui.find({ key: 'show' })).toBeUndefined()
    })
  }

  test(`Details opens the pane and Close closes it (${surface})`, async ($, on) => {
    const opened: string[] = []
    serve(on, BOARD, { open: id => opened.push(`open ${id}`), close: id => opened.push(`close ${id}`) })

    await $.command.run(RUN)
    const ui = await band($, surface)
    await ui.press({ key: 'details-PROJ-1' })
    expect((await ui.find({ key: 'details-PROJ-1' }))?.props.label).toBe('Close')
    expect((await ui.find({ key: 'details-PROJ-2' }))?.props.label).toBe('Details')
    await ui.press({ key: 'details-PROJ-1' })

    expect(opened).toEqual(['open starpulse-board', 'close starpulse-board'])
    expect((await ui.find({ key: 'details-PROJ-1' }))?.props.label).toBe('Details')
  })
}

test('terminal row: ID, title, AC bar and k/n, column, PR and its checks, buttons', async ($, on) => {
  serve(on, BOARD)

  await $.command.run(RUN)
  const ui = await band($, 'terminal')

  for (const text of ['PROJ-1', 'Add the verbs', '██████', '░░░░░░', '2/4', 'In Progress', '#392', 'PROJ-2', '████████████', '4/4', 'Review', '#388']) {
    expect(await ui.find({ type: 'Text', text }), text).toBeDefined()
  }
  expect(await checkColor(ui, 'PROJ-1')).toBe('#fbbf24')
  expect(await checkColor(ui, 'PROJ-2')).toBe('#34d399')
  expect((await ui.find({ key: 'hide' }))?.props.label).toBe('✕')
  expect((await ui.find({ key: 'details-PROJ-1' }))?.props.label).toBe('Details')
})

test('terminal row: a Needs attention reason replaces the title, a Waiting task names what it waits on', async ($, on) => {
  serve(
    on,
    board([
      ['waiting', 'Waiting', [task({ id: 'PROJ-3', title: 'Retro the milestone', waiting_on: ['PROJ-8', 'PROJ-9'], prs: [] })]],
      [
        'needs_attention',
        'Needs Attention',
        [task({ id: 'PROJ-4', title: 'Investigate the alert', pause_reason: 'Operator: confirm the target was retired', prs: [] })],
      ],
    ]),
  )

  await $.command.run(RUN)
  const ui = await band($, 'terminal')

  expect(await ui.find({ type: 'Text', text: 'waiting on PROJ-8, PROJ-9' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Retro the milestone' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: 'Operator: confirm the target was retired' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Investigate the alert' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: 'Needs attention' })).toBeDefined()
  expect(await ui.find({ key: 'checks-PROJ-3' })).toBeUndefined()
})

test('terminal row: no checked data draws a count without a bar, no criteria draws neither', async ($, on) => {
  serve(
    on,
    board([
      [
        'in_progress',
        'In Progress',
        [
          task({ id: 'PROJ-5', title: 'Text only', criteria: [{ text: 'One' }, { text: 'Two' }, { text: 'Three' }] }),
          task({ id: 'PROJ-6', title: 'Older starpulse', criteria: undefined }),
        ],
      ],
    ]),
  )

  await $.command.run(RUN)
  const ui = await band($, 'terminal')

  expect(await ui.find({ type: 'Text', text: '3 criteria' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /[█░]/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /\d\/\d/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: 'Older starpulse' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /criteria/ })).toBeDefined()
})

test('desktop row: one Svg carries the ID, title, bar, k/n, lane and PR, with alt text', async ($, on) => {
  serve(on, BOARD)

  await $.command.run(RUN)
  const ui = await band($, 'desktop')
  const svg = await drawn(ui)

  expect(svg?.alt).toBe('PROJ-1: In Progress, 2 of 4 criteria, PR #392 checks running')
  for (const text of ['PROJ-1', 'Add the verbs', '2/4', 'In Progress', '#392', '#fbbf24', '#0c1322']) {
    expect(svg?.source, text).toContain(text)
  }
  expect((await ui.find({ key: 'details-PROJ-1' }))?.props.label).toBe('Details')
  expect((await ui.find({ key: 'hide' }))?.props.label).toBe('✕')
})

test('desktop row: a Needs attention reason replaces the title; no checked data drops the bar', async ($, on) => {
  serve(
    on,
    board([
      [
        'needs_attention',
        'Needs Attention',
        [task({ id: 'PROJ-4', title: 'Investigate the alert', pause_reason: 'Operator: confirm the target was retired', criteria: [{ text: 'One' }], prs: [] })],
      ],
    ]),
  )

  await $.command.run(RUN)
  const svg = await drawn(await band($, 'desktop'))

  expect(svg?.source).toContain('Operator: confirm the target was retired')
  expect(svg?.source).not.toContain('Investigate the alert')
  expect(svg?.source).toContain('1 criterion')
  expect(svg?.source).not.toMatch(/\d\/\d/)
  expect(svg?.alt).toBe('PROJ-4: Needs attention, 1 criterion')
})

test('desktop row: a narrow band drops the title, then the PR; the ID, bar and count stay', async ($, on) => {
  serve(on, BOARD)

  await $.command.run(RUN)
  const svg = await drawn(await band($, 'desktop', { ...PROPS, bodyColumns: 36 }))

  expect(svg?.source).toContain('PROJ-1')
  expect(svg?.source).toContain('2/4')
  expect(svg?.source).not.toContain('Add the verbs')
  expect(svg?.source).not.toContain('#392')
})

test('desktop row: under reduced motion the Svg animation stops, and only a live lane or running check animates', async ($, on) => {
  const quiet = board([['review', 'Review', [task({ id: 'PROJ-2', title: 'Rotate the secret', prs: [{ url: `${PULL}/388`, checks: 'pass' }] })]]])
  let current = BOARD
  serve(on, '', { run: () => answer(0, current) })

  await $.command.run(RUN)
  const live = (await drawn(await band($, 'desktop')))?.source ?? ''
  const reduced = /@media \(prefers-reduced-motion: reduce\)\{\.t0,\.t1,\.t2,\.t3,\.live\{animation:none\}\}/
  expect(live).toMatch(reduced)
  expect(live).toContain('class="live"')

  current = quiet
  await $.command.run(RUN)
  const still = (await drawn(await band($, 'desktop')))?.source ?? ''

  expect(still).toMatch(reduced)
  expect(still).not.toContain('class="live"')
  expect(still).toContain('.t0,.t1,.t2,.t3{animation:none}')
})

test('terminal pane: ID, title, lane and holder, reason, criteria with ticks, PR and its checks', async ($, on) => {
  serve(
    on,
    board([
      [
        'needs_attention',
        'Needs Attention',
        [task({ id: 'PROJ-4', title: 'Investigate the alert', pause_reason: 'Operator: confirm it', holder: SESSION })],
      ],
    ]),
  )

  await $.command.run(RUN)
  const ui = await band($, 'terminal')
  await ui.press({ key: 'details-PROJ-4' })
  const pane_ = await pane($, 'terminal')

  for (const text of ['PROJ-4', 'Investigate the alert', 'Needs attention', 'Operator: confirm it', 'Acceptance criteria 2/4', '✓ Criterion 1', '○ Criterion 3', 'trantor-org/starpulse#392', 'checks running']) {
    expect(await pane_.find({ type: 'Text', text }), text).toBeDefined()
  }
  expect(await pane_.find({ type: 'Text', text: /held by session-1/ })).toBeDefined()
})

test('terminal pane: a task with no checked data lists its criteria without ticks', async ($, on) => {
  serve(on, board([['in_progress', 'In Progress', [task({ id: 'PROJ-5', title: 'Text only', criteria: [{ text: 'One' }, { text: 'Two' }], prs: [] })]]]))

  await $.command.run(RUN)
  await (await band($, 'terminal')).press({ key: 'details-PROJ-5' })
  const pane_ = await pane($, 'terminal')

  expect(await pane_.find({ type: 'Text', text: 'Acceptance criteria 2' })).toBeDefined()
  expect(await pane_.find({ type: 'Text', text: '· One' })).toBeDefined()
  expect(await pane_.find({ type: 'Text', text: /[✓○]/ })).toBeUndefined()
})

for (const surface of ['desktop', 'mobile'] as const) {
  test(`pane Svg: ID, title, lane and holder, reason, criteria list and PR (${surface})`, async ($, on) => {
    serve(
      on,
      board([
        [
          'needs_attention',
          'Needs Attention',
          [task({ id: 'PROJ-4', title: 'Investigate the alert', pause_reason: 'Operator: confirm it' })],
        ],
      ]),
    )

    await $.command.run(RUN)
    await (await band($, 'desktop')).press({ key: 'details-PROJ-4' })
    const svg = await drawn(await pane($, surface))

    for (const text of ['PROJ-4', 'Investigate the alert', 'Needs attention', 'held by session-1', 'Operator: confirm it', 'ACCEPTANCE CRITERIA', '2/4', 'Criterion 1', 'Criterion 4', 'trantor-org/starpulse#392', 'checks running']) {
      expect(svg?.source, text).toContain(text)
    }
    expect(svg?.alt).toContain('PROJ-4')
    expect(svg?.source).toMatch(/@media \(prefers-reduced-motion: reduce\)/)
  })
}

test('the pane shows the first held task when none was picked', async ($, on) => {
  serve(on, BOARD)

  await $.command.run(RUN)
  const svg = await drawn(await pane($, 'desktop'))

  expect(svg?.source).toContain('PROJ-1')
})

// Registered sessions besides the key files beside them: this one, one in tmux session task-7, an interactive one in no
// tmux pane (a desktop app session), and a background one in no tmux pane.
const REGISTRY: Record<string, object> = {
  '/home/me/.claude/sessions/100.json': { sessionId: SESSION, pid: 100, name: 'me', status: 'busy' },
  '/home/me/.claude/sessions/200.json': { sessionId: 'session-2', pid: 200, name: 'trantor-2', status: 'busy' },
  '/home/me/.claude/sessions/300.json': { sessionId: 'session-3', pid: 300, name: 'Fix the gate', status: 'idle', kind: 'interactive' },
  '/home/me/.claude/sessions/400.json': { sessionId: 'abcd1234-5678', pid: 400, name: 'Check the alert', status: 'idle', kind: 'bg' },
}

// Stands in for filetree: a second plugin that opens its own pane a second into the session, then one more.
const FILES = {
  name: 'files',
  register(on: On) {
    on('session.start', async ($, e, next) => {
      $.clock.after(1000, async () => {
        await $.ui.open({ id: 'filetree', title: 'Files' })
        await $.ui.open({ id: 'other', title: 'Other' })
      })

      return next(e)
    })
  },
}

// A child's output the test writes as it goes; end() exits the child, as a server restart ends curl.
const feed = () => {
  const queue: (string | null)[] = []
  let wake = () => {}
  const push = (text: string | null) => {
    queue.push(text)
    wake()
  }
  return {
    write: (text: string) => push(text),
    // One frame of the held-task stream, carrying `board` as the server sends it.
    held: (board: string) => push(`event: held\ndata: ${board}\n\n`),
    end: () => push(null),
    async *chunks() {
      while (true) {
        while (!queue.length) await new Promise<void>(r => (wake = r))
        const text = queue.shift()
        if (text === null || text === undefined) return { value: { code: 0, signal: null } }
        yield { stream: 'stdout' as const, text }
      }
    },
  }
}
type Feed = ReturnType<typeof feed>

type Host = {
  switched?: string[][]
  opened?: string[]
  ran?: string[][]
  spawned?: string[][]
  everys?: number[]
  held?: Feed[]
  watch?: Feed
  registry?: Record<string, object>
  hasClock?: boolean
  isAlone?: boolean
  board?: () => Promise<ReturnType<typeof answer>> | ReturnType<typeof answer>
  posted?: string[][]
  post?: (argv: readonly string[]) => ReturnType<typeof answer>
  toasts?: string[]
}

// Stands in for the engine and the host: the registry above, tmux session task-7 holding pid 200, a held-task stream
// that sends nothing until the test feeds it, and a sessions-folder watch likewise.
// A test that mocks the clock says so with hasClock, since mock.clock answers clock.every itself.
const sessionsHost = (on: On, host: Host = {}) => {
  const registry = () => host.registry ?? (host.isAlone ? {} : REGISTRY)
  on('ui.render', ($, e) => h($.ui.resolve(e).Box, { key: 'engine' }) as RenderElement)
  on('session.id', () => ({ value: SESSION }))
  on('session.start', ($, e) => e)
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  if (!host.hasClock) {
    on('clock.every', ($, e) => {
      host.everys?.push(e.ms)
      return { value: undefined }
    })
  }
  if (!host.hasClock) on('clock.now', () => ({ value: 1_800_000_000_000 }))
  on('env.get', ($, e) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  if (host.toasts) on('ui.toast', ($, e) => {
    host.toasts?.push(e.text)
    return { value: undefined }
  })
  on('ui.open', ($, e) => {
    host.opened?.push(`${e.id} focus=${e.focus === true}`)
    return { value: { isPlaced: true as const } }
  })
  on('ui.close', ($, e) => {
    host.opened?.push(`close ${e.id}`)
    return { value: undefined }
  })
  on('fs.list', () => ({
    value: [...Object.keys(registry()), '/home/me/.claude/sessions/200.abc.key'].map(p => ({
      name: p.split('/').at(-1)!,
      kind: 'file' as const,
      size: 1,
      mtimeMs: 0,
      isLink: false,
    })),
  }))
  on('fs.read', ($, e) => ({ value: JSON.stringify(registry()[e.path]) }))
  on('process.run', ($, e) => {
    host.ran?.push([...e.argv])
    if (e.argv[0] === 'tmux' && e.argv[1] === 'list-panes') return answer(0, '200 task-7\n999 scratch\n')
    if (e.argv[0] === 'tmux') {
      host.switched?.push([...e.argv])
      return answer(0, '')
    }
    if (e.argv[0] === 'curl') {
      host.posted?.push([...e.argv])
      return host.post?.(e.argv) ?? answer(0, '{}\n200')
    }
    return host.board?.() ?? answer(0, JSON.stringify({ columns: [] }))
  })
  const watch = host.watch ?? feed()
  on('process.spawn', async function* ($, e) {
    host.spawned?.push([...e.argv])
    const child = e.argv[0] === 'inotifywait' ? watch : (host.held?.shift() ?? feed())
    return yield* child.chunks()
  })
}

const start = async ($: any, surface: string) => {
  await $.session.start({ cwd: '/work', surface, isInteractive: true })
  await settle()
}

const sessionsPane = ($: any, surface: string, placement = 'dock') =>
  $.ui.mount({ plugin: 'starpulse-board', surface, component: 'Pane', props: { ...PANE_PROPS, placement }, requestId: 'starpulse-sessions' })

// The whole Board as `starpulse board` prints it: a Ready task, one In Progress held by session-2 (tmux session task-7),
// and the New and Done columns the Board tab leaves out.
const KANBAN = board([
  ['new', 'New', [task({ id: 'TASK-9', title: 'Unshaped' })]],
  ['ready', 'Ready', [task({ id: 'TASK-10', title: 'Ready one', assignee: '@agent-standard-medium', moves: { in_progress: { allowed: true }, waiting: { allowed: true } } })]],
  ['waiting', 'Waiting', []],
  ['in_progress', 'In Progress', [task({ id: 'TASK-7', title: 'Busy one', holder: 'session-2', moves: { review: { allowed: true }, ready: { allowed: false, reason: 'made by operator, not agent' } } })]],
  ['review', 'Review', []],
  ['needs_attention', 'Needs Attention', []],
  ['done', 'Done', [task({ id: 'TASK-1', title: 'Old' })]],
])

const kanbanPane = ($: any) =>
  $.ui.mount({ plugin: 'starpulse-board', surface: 'terminal', component: 'Pane', props: { ...PANE_PROPS, placement: 'dock' }, requestId: 'starpulse-kanban' })

// The Board tab, opened from /kanban the way a person would. Each test unmounts its drawing.
const openKanban = async ($: any, on: On, host: Host = {}) => {
  sessionsHost(on, { board: () => answer(0, KANBAN), ...host })
  await start($, 'terminal')
  await $.command.run({ ...RUN, command: 'kanban' })
  await settle()
  return kanbanPane($)
}

// The JSON body a curl call sends.
const sent = (argv: readonly string[]) => JSON.parse(argv[argv.indexOf('--data') + 1] ?? 'null')

test('the Board tab lists the open lanes in order with their counts, Ready and Waiting folded', async ($, on) => {
  const ui = await openKanban($, on)

  const lanes = (await ui.findAll({ type: 'Button' })).map((b: any) => String(b.props.label)).filter((label: string) => /^[▾▸] /.test(label))
  expect(lanes).toEqual(['▾ In Progress 1', '▾ Review 0', '▾ Needs Attention 0', '▸ Ready 1', '▸ Waiting 0'])
  expect((await ui.find({ key: 'task:TASK-7' }))?.props.label).toBe('TASK-7 Busy one')
  expect(await ui.find({ key: 'task:TASK-10' })).toBeUndefined()
  expect(await ui.find({ key: 'task:TASK-1' })).toBeUndefined()
  await ui.unmount()
})

// A pane body scrolls its tree, so flexGrow has no height to fill: the root takes the body's rows to paint the dock black to its floor.
for (const [state, exitCode] of [['lanes', 0], ['a failed read', 1]] as const) {
  test(`the Board tab paints black down the whole dock body with ${state}`, async ($, on) => {
    const ui = await openKanban($, on, { board: () => answer(exitCode, exitCode ? '' : KANBAN) })

    expect((await ui.find({ key: 'board-fill' }))?.props).toMatchObject({ minHeight: PANE_PROPS.scroll.bodyRows, backgroundColor: '#000000' })
    await ui.unmount()
  })
}

test('pressing a lane header folds and unfolds it', async ($, on) => {
  const ui = await openKanban($, on)

  await ui.press({ key: 'lane:in_progress' })
  await ui.press({ key: 'lane:ready' })

  expect((await ui.find({ key: 'lane:in_progress' }))?.props.label).toBe('▸ In Progress 1')
  expect(await ui.find({ key: 'task:TASK-7' })).toBeUndefined()
  expect((await ui.find({ key: 'task:TASK-10' }))?.props.label).toBe('TASK-10 Ready one')
  await ui.unmount()
})

test('a Ready task starts a session through StarPulse, then switches tmux to it', async ($, on) => {
  const posted: string[][] = []
  const switched: string[][] = []
  const ui = await openKanban($, on, { posted, switched })

  await ui.press({ key: 'lane:ready' })
  await ui.press({ key: 'task:TASK-10' })
  expect((await ui.find({ key: 'session:TASK-10' }))?.props.label).toBe('Start session')
  await ui.press({ key: 'session:TASK-10' })

  expect(posted.map(a => a.find(x => x.startsWith('http')))).toEqual(['http://localhost:8766/api/start'])
  expect(sent(posted[0]!)).toEqual({ task: 'TASK-10', assignee: '@agent-standard-medium', harness: 'claude' })
  expect(switched).toEqual([['tmux', 'switch-client', '-t', 'task-10']])
  await ui.unmount()
})

test('an In Progress task goes to its live session without starting one', async ($, on) => {
  const posted: string[][] = []
  const switched: string[][] = []
  const ui = await openKanban($, on, { posted, switched })

  await ui.press({ key: 'task:TASK-7' })
  expect((await ui.find({ key: 'session:TASK-7' }))?.props.label).toBe('Go to session')
  await ui.press({ key: 'session:TASK-7' })

  expect(posted).toEqual([])
  expect(switched).toEqual([['tmux', 'switch-client', '-t', 'task-7']])
  await ui.unmount()
})

test('a move button moves the task through StarPulse and rereads the Board', async ($, on) => {
  const posted: string[][] = []
  let reads = 0
  const ui = await openKanban($, on, {
    posted,
    board: () => {
      reads++
      return answer(0, KANBAN)
    },
  })

  await ui.press({ key: 'task:TASK-7' })
  expect((await ui.find({ key: 'move:TASK-7:review' }))?.props.label).toBe('→ Review')
  const before = reads
  await ui.press({ key: 'move:TASK-7:review' })
  await settle()

  expect(posted.map(a => a.find(x => x.startsWith('http')))).toEqual(['http://localhost:8766/api/move'])
  expect(sent(posted[0]!)).toEqual({ task: 'TASK-7', to: 'review' })
  expect(reads).toBeGreaterThan(before)
  await ui.unmount()
})

test('a refused move shows the server\'s reason as a toast', async ($, on) => {
  const toasts: string[] = []
  const ui = await openKanban($, on, { toasts, post: () => answer(0, '{"error": "TASK-7 cannot move from in_progress to review"}\n409') })

  await ui.press({ key: 'task:TASK-7' })
  await ui.press({ key: 'move:TASK-7:review' })

  expect(toasts).toEqual(['TASK-7 cannot move from in_progress to review'])
  await ui.unmount()
})

test('the band\'s Board button opens the Board tab with the keys', async ($, on) => {
  const opened: string[] = []
  sessionsHost(on, { opened })

  const ui = await band($, 'terminal')
  await start($, 'terminal')
  await ui.press({ key: 'kanban' })

  expect(opened.at(-1)).toBe('starpulse-kanban focus=true')
  await ui.unmount()
})

test('a Sessions pane placed inline closes itself and draws nothing, as Files does', async ($, on) => {
  const opened: string[] = []
  sessionsHost(on, { opened })

  await start($, 'terminal')
  const ui = await sessionsPane($, 'terminal', 'inline')
  await settle()

  expect(await ui.find({ key: 'session:session-2' })).toBeUndefined()
  expect(opened.at(-1)).toBe('close starpulse-sessions')
})

for (const surface of ['terminal', 'desktop'] as const) {
  test(`the band counts the other sessions on one line, with no button per session (${surface})`, async ($, on) => {
    sessionsHost(on)

    const ui = await band($, surface)
    await start($, surface)

    expect((await ui.find({ key: 'sessions' }))?.props.label).toBe('1 working · 2 idle')
    expect(await ui.find({ key: 'session:session-2' })).toBeUndefined()
  })

  test(`a new session opens the Sessions pane without taking the keys (${surface})`, async ($, on) => {
    const opened: string[] = []
    sessionsHost(on, { opened })

    await start($, surface)

    expect(opened).toEqual(['starpulse-sessions focus=false'])
  })

  test(
    `the first pane another plugin opens at start is reopened under Sessions, once (${surface})`,
    { plugins: [FILES] },
    async ($, on) => {
      const opened: string[] = []
      const clock = mock.clock(on)
      sessionsHost(on, { opened, hasClock: true })

      await start($, surface)
      await clock.advance(1000)

      expect(opened).toEqual([
        'starpulse-sessions focus=false',
        'filetree focus=false',
        'other focus=false',
        'close starpulse-sessions',
        'starpulse-sessions focus=false',
      ])
    },
  )

  test(`a pane opened after the first prompt keeps the dock (${surface})`, { plugins: [FILES] }, async ($, on) => {
    const opened: string[] = []
    const clock = mock.clock(on)
    sessionsHost(on, { opened, hasClock: true })
    on('prompt.submit', ($, e) => e)

    await start($, surface)
    await $.prompt.submit({ text: 'hi', wait: false, origin: { kind: 'composer' } })
    await clock.advance(1000)

    expect(opened).toEqual(['starpulse-sessions focus=false', 'filetree focus=false', 'other focus=false'])
  })

  test(`a new session with no other session opens no pane (${surface})`, async ($, on) => {
    const opened: string[] = []
    sessionsHost(on, { opened, isAlone: true })

    await start($, surface)

    expect(opened).toEqual([])
  })

  test(`pressing the count opens the Sessions pane with the keys (${surface})`, async ($, on) => {
    const opened: string[] = []
    sessionsHost(on, { opened })

    const ui = await band($, surface)
    await start($, surface)
    await ui.press({ key: 'sessions' })

    expect(opened.at(-1)).toBe('starpulse-sessions focus=true')
  })

  test(`the Sessions pane lists every session with its status, this one marked (${surface})`, async ($, on) => {
    sessionsHost(on)

    await start($, surface)
    const ui = await sessionsPane($, surface)
    const label = async (key: string) => (await ui.find({ key }))?.props.label as string

    expect(await label('session:session-2')).toMatch(/^trantor-2, working, /)
    expect(await label('session:abcd1234-5678')).toMatch(/^Check the alert, background, idle, /)
    expect(await label('session:session-3')).toMatch(/^Fix the gate, idle, /)
    expect(await label(`session:${SESSION}`)).toMatch(/^me, you, working, /)
  })

  test(`pressing a session in tmux switches the tmux client to it (${surface})`, async ($, on) => {
    const switched: string[][] = []
    sessionsHost(on, { switched })

    await start($, surface)
    const ui = await sessionsPane($, surface)
    await ui.press({ key: 'session:session-2' })

    expect(switched).toEqual([['tmux', 'switch-client', '-t', 'task-7']])
  })

  test(`pressing a background session attaches it in a tmux session and switches to it (${surface})`, async ($, on) => {
    const switched: string[][] = []
    sessionsHost(on, { switched })

    await start($, surface)
    const ui = await sessionsPane($, surface)
    await ui.press({ key: 'session:abcd1234-5678' })

    expect(switched).toEqual([
      ['tmux', 'new-session', '-A', '-d', '-s', 'bg-abcd1234', 'claude', 'attach', 'abcd1234'],
      ['tmux', 'switch-client', '-t', 'bg-abcd1234'],
    ])
  })
}

for (const surface of ['terminal', 'desktop'] as const) {
  test(`the band draws what the held-task stream sends, with no starpulse run (${surface})`, async ($, on) => {
    const stream = feed()
    const ran: string[][] = []
    const spawned: string[][] = []
    sessionsHost(on, { held: [stream], ran, spawned })

    const ui = await band($, surface)
    await start($, surface)
    stream.held(BOARD)
    await settle()

    expect(await ui.find({ key: 'details-PROJ-1' })).toBeDefined()
    expect(await ui.find({ key: 'details-PROJ-2' })).toBeDefined()
    expect(spawned.find(argv => argv[0] === 'curl')?.at(-1)).toBe('http://localhost:8766/api/held?holder=session-1')
    expect(ran.filter(argv => argv.join(' ').includes('--holder'))).toEqual([])
  })

  test(`a tool call and a turn's end read no board (${surface})`, async ($, on) => {
    const ran: string[][] = []
    sessionsHost(on, { ran })
    on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: '', stderr: '' } }))
    on('turn.complete', () => ({ text: '' }))

    await start($, surface)
    const before = ran.length
    await $.tool.call({ tool: 'Bash', command: 'claim the task' })
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't-1', reason: 'answer' })
    await settle()

    expect(ran.slice(before)).toEqual([])
  })

  test(`a held-task stream that ends is opened again and its frames draw (${surface})`, async ($, on) => {
    const [first, second] = [feed(), feed()]
    const clock = mock.clock(on)
    sessionsHost(on, { held: [first, second], hasClock: true })

    const ui = await band($, surface)
    await start($, surface)
    first.held(board([['in_progress', 'In Progress', [task({ id: 'PROJ-1', title: 'Add the verbs' })]]]))
    first.end()
    await settle()
    await clock.advance(30_000)
    second.held(board([['review', 'Review', [task({ id: 'PROJ-9', title: 'After the restart' })]]]))
    await settle()

    expect(await ui.find({ key: 'details-PROJ-9' })).toBeDefined()
    expect(await ui.find({ key: 'details-PROJ-1' })).toBeUndefined()
  })

  test(`a change in the sessions folder rereads the registry, and no timer runs (${surface})`, async ($, on) => {
    const watch = feed()
    const everys: number[] = []
    const spawned: string[][] = []
    const host: Host = { watch, everys, spawned, registry: {} }
    sessionsHost(on, host)

    const ui = await band($, surface)
    await start($, surface)
    const before = await ui.find({ key: 'sessions' })
    host.registry = REGISTRY
    watch.write('200.json\n')
    await settle()

    expect(before).toBeUndefined()
    expect((await ui.find({ key: 'sessions' }))?.props.label).toBe('1 working · 2 idle')
    expect(spawned.find(argv => argv[0] === 'inotifywait')?.at(-1)).toBe('/home/me/.claude/sessions')
    expect(everys).toEqual([])
  })
}

// The Nerd Font v3 icons the mod draws by default, and the plain characters `glyphs: plain` swaps in.
const NERD = { inProgress: '', pending: '', pass: '', move: '', refresh: '', board: '', go: '', pr: '' }
const PLAIN = { inProgress: '▶', pending: '●', pass: '✓', move: '→', refresh: '↻', board: '▦', go: '↗', pr: '#' }

const LANE_COLORS = { in_progress: '#fbbf24', review: '#a78bfa', needs_attention: '#fb7185', ready: '#60a5fa', waiting: '#94a3b8', done: '#34d399' }

// Every lane, each with one task that holds a PR and criteria, for the Board pane's colours.
const COLOURED = board([
  ['ready', 'Ready', [task({ id: 'TASK-10', title: 'Ready one', moves: { in_progress: { allowed: true } } })]],
  ['waiting', 'Waiting', [task({ id: 'TASK-11', title: 'Waits', waiting_on: ['TASK-7'] })]],
  ['in_progress', 'In Progress', [task({ id: 'TASK-7', title: 'Busy one', holder: 'session-2', moves: { review: { allowed: true }, done: { allowed: true } } })]],
  ['review', 'Review', [task({ id: 'TASK-12', title: 'Reviewed', prs: [{ url: `${PULL}/9`, checks: 'pass' }] })]],
  ['needs_attention', 'Needs Attention', [task({ id: 'TASK-13', title: 'Stuck', pause_reason: 'Operator: pick one', prs: [] })]],
])

// Every Text of a tree as [text, color, bold], read once: each `find` costs a round trip and a test has five seconds.
type Seen = { text: string; color?: string; bold?: boolean }[]
const texts = async (tree: any): Promise<Seen> =>
  (await tree.findAll({ type: 'Text' })).map((el: any) => ({ text: el.children.join(''), color: el.props.color, bold: el.props.bold }))
const has = (seen: Seen, text: string) => seen.some(t => t.text === text)
const colorOf = (seen: Seen, text: string) => seen.find(t => t.text === text)?.color

for (const glyphs of ['nerd', 'plain'] as const) {
  const set = glyphs === 'nerd' ? NERD : PLAIN

  test(`glyphs=${glyphs}: the band draws ${glyphs} icons`, { options: { glyphs } }, async ($, on) => {
    const stream = feed()
    sessionsHost(on, { held: [stream] })
    await start($, 'terminal')
    stream.held(BOARD)
    await settle()
    const held = await texts(await band($, 'terminal'))

    // The held task's lane icon and PR checks glyph, and the summary line's Board icon.
    expect(has(held, set.inProgress), 'lane icon').toBe(true)
    expect(has(held, set.pending), 'checks glyph').toBe(true)
    expect(has(held, `${set.board} Board`), 'board icon').toBe(true)
  })

  test(`glyphs=${glyphs}: the Board tab draws ${glyphs} icons`, { options: { glyphs } }, async ($, on) => {
    const ui = await openKanban($, on, { board: () => answer(0, COLOURED) })
    await ui.press({ key: 'task:TASK-7' })
    const tab = await texts(ui)

    // Refresh, lane icon, PR glyph, then the move arrow and the go icon once a task is picked.
    expect(has(tab, set.refresh), 'refresh').toBe(true)
    expect(has(tab, set.inProgress), 'lane icon').toBe(true)
    expect(has(tab, `${set.move} Review`), 'move arrow').toBe(true)
    expect(has(tab, `${set.go} Go to session`), 'go icon').toBe(true)
    expect(has(tab, `${set.pr} #392`), 'pr icon').toBe(true)
    await ui.unmount()
  })
}

test('the Board tab colours each lane header and icon by its lane', async ($, on) => {
  const ui = await openKanban($, on, { board: () => answer(0, COLOURED) })
  const seen = await texts(ui)

  const names = { in_progress: 'IN PROGRESS', review: 'REVIEW', needs_attention: 'NEEDS ATTENTION', ready: 'READY', waiting: 'WAITING' } as const
  for (const [lane, name] of Object.entries(names)) {
    const header = seen.find(t => t.text === name)
    expect(header?.color, name).toBe(LANE_COLORS[lane as keyof typeof LANE_COLORS])
    expect(header?.bold, name).toBe(true)
  }
  // The lane's count sits beside it, dimmer.
  expect(colorOf(seen, '1')).toBe('#6b7a93')
  await ui.unmount()
})

test('a Board row draws the ID, title, four-cell bar and PR check icon', async ($, on) => {
  const ui = await openKanban($, on, { board: () => answer(0, COLOURED) })

  const seen = await texts(ui)
  expect(colorOf(seen, 'TASK-7')).toBe('#94a3b8')
  expect(colorOf(seen, 'Busy one')).toBe('#dbe4f3')
  expect(colorOf(seen, '██')).toBe('#fbbf24')
  expect(colorOf(seen, '░░')).toBe('#334155')
  expect(colorOf(seen, NERD.pending)).toBe('#fbbf24')
  // A reason replaces the title in fail-text; a waiting task says what it waits on.
  expect(colorOf(seen, 'Operator: pick one')).toBe('#fda4af')
  await ui.press({ key: 'lane:waiting' })
  expect(colorOf(await texts(ui), 'waiting on TASK-7')).toBe('#94a3b8')
  await ui.unmount()
})

test('a picked task opens its title, holder, criteria, PR and actions coloured by target lane', async ($, on) => {
  const ui = await openKanban($, on, { board: () => answer(0, COLOURED) })

  await ui.press({ key: 'task:TASK-7' })
  const seen = await texts(ui)
  const buttons = await ui.findAll({ type: 'Button' })
  const first = (key: string) => (buttons.find((b: any) => b.key === key) as any)?.children[0]?.props.color

  expect(seen.filter(t => t.text === 'Busy one').length, 'row and detail').toBe(2)
  expect(colorOf(seen, 'task-7'), 'holder').toBe('#94a3b8')
  expect(colorOf(seen, '2/4 criteria')).toBe('#6b7a93')
  expect(colorOf(seen, `${NERD.pr} #392`)).toBe('#a78bfa')
  expect(colorOf(seen, 'checks running')).toBe('#fbbf24')
  expect(first('session:TASK-7'), 'Go to session').toBe('#34d399')
  expect(first('move:TASK-7:review')).toBe('#a78bfa')
  expect(first('move:TASK-7:done')).toBe('#34d399')
  await ui.press({ key: 'task:TASK-7' })
  expect(await ui.find({ key: 'session:TASK-7' })).toBeUndefined()
  await ui.unmount()
})

test('a move to Done that StarPulse refuses toasts its reason and leaves the Board as read', async ($, on) => {
  const toasts: string[] = []
  const ui = await openKanban($, on, {
    toasts,
    board: () => answer(0, COLOURED),
    post: () => answer(0, '{"error": "only the operator moves TASK-7 to Done"}\n409'),
  })

  await ui.press({ key: 'task:TASK-7' })
  await ui.press({ key: 'move:TASK-7:done' })

  expect(toasts).toEqual(['only the operator moves TASK-7 to Done'])
  expect(await ui.find({ key: 'task:TASK-7' })).toBeDefined()
  await ui.unmount()
})

// No fill: a `plain` Button draws no chrome and nothing sets a background, so the terminal's black shows through.
// The one exception is the Board pane's root Box, filled black to cover the dock's own grey (the operator's call).
const fills = async (tree: any, root?: string) => {
  const buttons = await tree.findAll({ type: 'Button' })
  expect(buttons.length).toBeGreaterThan(0)
  for (const b of buttons) expect(b.props.plain, String(b.props.label)).toBe(true)
  const filled: string[] = []
  for (const type of ['Box', 'Text', 'Button'])
    for (const el of await tree.findAll({ type })) if (el.props.backgroundColor !== undefined) filled.push(`${type} ${el.props.backgroundColor}`)
  expect(filled).toEqual(root ? [`Box ${root}`] : [])
}

test('the Board tab fills its root black to cover the dock grey, every Button is plain and nothing else sets a background', async ($, on) => {
  const ui = await openKanban($, on, { board: () => answer(0, COLOURED) })
  await ui.press({ key: 'task:TASK-7' })

  await fills(ui, '#000000')
  await ui.unmount()
})

test('the band draws no fill: every Button is plain and no element sets a background', async ($, on) => {
  const stream = feed()
  sessionsHost(on, { board: () => answer(0, COLOURED), held: [stream] })
  await start($, 'terminal')
  stream.held(BOARD)
  await settle()

  await fills(await band($, 'terminal'))
})
