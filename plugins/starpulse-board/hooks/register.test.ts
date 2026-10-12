import type { RenderElement } from 'claude-code'
import { expect, test } from 'claude-code/testing'

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

  test(`the band appears after a tool call mid-turn, before the turn ends (${surface})`, async ($, on) => {
    let current = board([])
    serve(on, '', { run: () => answer(0, current) })
    on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: '', stderr: '' } }))

    const ui = await band($, surface)
    current = BOARD
    await $.tool.call({ tool: 'Bash', command: 'claim the task' })
    await settle()

    expect(await ui.find({ key: 'hide' })).toBeDefined()
  })

  test(`an older starpulse on PATH falls back to ~/.local/bin (${surface})`, async ($, on) => {
    const argv0: string[] = []
    serve(on, BOARD, {
      run: e => {
        argv0.push(e.argv[0])
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
        argv0.push(e.argv[0])
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

  for (const text of ['PROJ-1', 'Add the verbs', '██████░░░░░░', '2/4', 'In Progress', '#392', 'PROJ-2', '████████████', '4/4', 'Review', '#388']) {
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
