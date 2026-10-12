import type { RenderElement } from 'claude-code'
import { expect, test } from 'claude-code/testing'

const BOARD = JSON.stringify({
  columns: [
    { state: 'in_progress', name: 'In Progress', tasks: [{ id: 'PROJ-1', title: 'Add the verbs' }] },
    { state: 'review', name: 'Review', tasks: [{ id: 'PROJ-2', title: 'Rotate the secret' }] },
  ],
})

const SESSION = 'session-1'

const PROPS = {
  hasSurvey: false,
  isWorking: false,
  maxRows: 4,
  bodyColumns: 80,
  scroll: { offset: 0, bodyRows: 20 },
  view: {},
}

const RUN = { command: 'board', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as const

// Lets a refresh the engine did not await finish.
const settle = async () => {
  for (let i = 0; i < 20; i++) await new Promise(r => setTimeout(r, 0))
}

const answer = (exitCode: number, stdout: string) => ({
  value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})

for (const surface of ['terminal', 'desktop'] as const) {
  test(`/board lists and the band shows the tasks this session holds (${surface})`, async ($, on) => {
    let argv: readonly string[] = []
    on('ui.render', ($, e) => h($.ui.resolve(e).Box, { key: 'engine' }) as RenderElement)
    on('session.id', () => ({ value: SESSION }))
    on('process.run', ($, e) => {
      argv = e.argv
      return answer(0, BOARD)
    })

    const { text } = await $.command.run(RUN)
    const ui = await $.ui.mount({ plugin: 'starpulse-board', surface, component: 'AbovePrompt', props: PROPS })

    expect(argv).toEqual(['starpulse', 'board', '--holder', SESSION])
    expect(text).toBe('PROJ-1 [In Progress] Add the verbs\nPROJ-2 [Review] Rotate the secret')
    expect(await ui.find({ text: 'Tasks: PROJ-1 In Progress · PROJ-2 Review ' })).toBeDefined()
  })

  test(`the band appears after a tool call mid-turn, before the turn ends (${surface})`, async ($, on) => {
    let board = JSON.stringify({ columns: [] })
    on('ui.render', ($, e) => h($.ui.resolve(e).Box, { key: 'engine' }) as RenderElement)
    on('session.id', () => ({ value: SESSION }))
    on('process.run', () => answer(0, board))
    on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: '', stderr: '' } }))

    const ui = await $.ui.mount({ plugin: 'starpulse-board', surface, component: 'AbovePrompt', props: PROPS })
    board = BOARD
    await $.tool.call({ tool: 'Bash', command: 'claim the task' })
    await settle()

    expect(await ui.find({ text: 'Tasks: PROJ-1 In Progress · PROJ-2 Review ' })).toBeDefined()
  })

  test(`an older starpulse on PATH falls back to ~/.local/bin (${surface})`, async ($, on) => {
    const argv0: string[] = []
    on('ui.render', ($, e) => h($.ui.resolve(e).Box, { key: 'engine' }) as RenderElement)
    on('session.id', () => ({ value: SESSION }))
    on('env.get', () => ({ value: '/home/me' }))
    on('process.run', ($, e) => {
      argv0.push(e.argv[0])
      return e.argv[0] === 'starpulse' ? answer(2, '') : answer(0, BOARD)
    })

    const { text } = await $.command.run(RUN)

    expect(argv0).toEqual(['starpulse', '/home/me/.local/bin/starpulse'])
    expect(text).toBe('PROJ-1 [In Progress] Add the verbs\nPROJ-2 [Review] Rotate the secret')
  })

  test(`no starpulse on PATH falls back to ~/.local/bin and draws the band (${surface})`, async ($, on) => {
    const argv0: string[] = []
    on('ui.render', ($, e) => h($.ui.resolve(e).Box, { key: 'engine' }) as RenderElement)
    on('session.id', () => ({ value: SESSION }))
    on('env.get', () => ({ value: '/home/me' }))
    on('process.run', ($, e) => {
      argv0.push(e.argv[0])
      if (e.argv[0] === 'starpulse') {
        throw new Error('ENOENT: Executable not found in $PATH: "starpulse"')
      }
      return answer(0, BOARD)
    })

    const { text } = await $.command.run(RUN)
    const ui = await $.ui.mount({ plugin: 'starpulse-board', surface, component: 'AbovePrompt', props: PROPS })

    expect(argv0).toEqual(['starpulse', '/home/me/.local/bin/starpulse'])
    expect(text).toBe('PROJ-1 [In Progress] Add the verbs\nPROJ-2 [Review] Rotate the secret')
    expect(await ui.find({ text: 'Tasks: PROJ-1 In Progress · PROJ-2 Review ' })).toBeDefined()
  })

  test(`Hide takes the band down until /board (${surface})`, async ($, on) => {
    on('ui.render', ($, e) => h($.ui.resolve(e).Box, { key: 'engine' }) as RenderElement)
    on('session.id', () => ({ value: SESSION }))
    on('process.run', () => answer(0, BOARD))

    await $.command.run(RUN)
    const ui = await $.ui.mount({ plugin: 'starpulse-board', surface, component: 'AbovePrompt', props: PROPS })
    await ui.press({ key: 'hide' })

    expect(await ui.find({ key: 'hide' })).toBeUndefined()
    await $.command.run(RUN)
    expect(await ui.find({ key: 'hide' })).toBeDefined()
  })

  for (const [why, exitCode, stdout] of [
    ['no server', 3, ''],
    ['no held task', 0, JSON.stringify({ columns: [{ state: 'ready', name: 'Ready', tasks: [] }] })],
  ] as const) {
    test(`no band with ${why} (${surface})`, async ($, on) => {
      on('ui.render', ($, e) => h($.ui.resolve(e).Box, { key: 'engine' }) as RenderElement)
    on('session.id', () => ({ value: SESSION }))
      on('process.run', () => answer(exitCode, stdout))

      const { text } = await $.command.run(RUN)
      const ui = await $.ui.mount({ plugin: 'starpulse-board', surface, component: 'AbovePrompt', props: PROPS })

      expect(text).toBe(exitCode ? '`starpulse board` failed: is the StarPulse server running?' : 'This session holds no tasks.')
      expect(await ui.find({ key: 'hide' })).toBeUndefined()
    })
  }
}
