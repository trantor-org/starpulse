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
    const { exitCode, stdout } = await $.process.run(['starpulse', 'board', '--holder', session])
    if (exitCode !== 0) {
      return null
    }
    const board = JSON.parse(stdout) as Board

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
