import { atom, read, update } from 'claude-code'
import type { EngineInterface as Engine, Register } from 'claude-code'
import type { HeldTask } from '../types'

const tasks = atom({ plugin: 'starpulse-board', key: 'tasks' } as const, null)
const isHidden = atom({ plugin: 'starpulse-board', key: 'isHidden' } as const, false)

type Board = { columns: { name: string; tasks: { id: string; title: string }[] }[] }

// The tasks this session last claimed, from the StarPulse server `starpulse board` reads; null when it cannot be read.
const held = async ($: Engine): Promise<HeldTask[] | null> => {
  try {
    const session = await $.session.id()
    const args = ['board', '--holder', session]
    // A start failure counts as a failed run: a non-login PATH (a Desktop SSH session's) lacks ~/.local/bin.
    const run = (argv0: string) => $.process.run([argv0, ...args]).catch(() => null)
    let ran = await run('starpulse')
    if (ran?.exitCode !== 0) {
      // A virtualenv on PATH can hold a starpulse older than --holder; the user-wide install is current.
      ran = await run(`${await $.env.get('HOME')}/.local/bin/starpulse`)
    }
    if (ran?.exitCode !== 0) {
      return null
    }
    const board = JSON.parse(ran.stdout) as Board

    return board.columns.flatMap(c => c.tasks.map(t => ({ id: t.id, title: t.title, column: c.name })))
  } catch {
    return null
  }
}

const refresh = async ($: Engine) => {
  const found = await held($)
  await update($, tasks, () => found)

  return found
}

// Refreshes without holding up the caller, one read at a time, rereading once if a call came in during it.
let reading: Promise<unknown> | null = null
let isStale = false
const refreshSoon = ($: Engine) => {
  if (reading) {
    isStale = true
    return
  }
  reading = refresh($).finally(() => {
    reading = null
    if (isStale) {
      isStale = false
      refreshSoon($)
    }
  })
}

const line = (found: HeldTask[]) => `Tasks: ${found.map(t => `${t.id} ${t.column}`).join(' · ')}`

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'board', description: 'List the Board tasks this session holds' })
    void refresh($)

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const ran = await next(e)
    await refresh($)

    return ran
  })

  // A session claims its task inside a turn, often its first and longest, so a tool call can change what it holds.
  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    refreshSoon($)

    return ran
  })

  on('command.run', { command: 'board' }, async $ => {
    await update($, isHidden, () => false)
    const found = await refresh($)
    if (found === null) {
      return { text: '`starpulse board` failed: is the StarPulse server running?' }
    }

    return {
      text: found.length ? found.map(t => `${t.id} [${t.column}] ${t.title}`).join('\n') : 'This session holds no tasks.',
    }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const found = await read($, tasks)
    if (e.props.hasSurvey || !found?.length || (await read($, isHidden))) {
      return next(e)
    }

    const { Box, Button, Text } = $.ui.resolve(e)

    return (
      <Box>
        <Text dimColor>{line(found)} </Text>
        <Button key="hide" label="Hide" onPress={() => update($, isHidden, () => true)} />
      </Box>
    )
  })
}
