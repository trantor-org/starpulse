import { atom, read, update } from 'claude-code'
import type { ElementTable, EngineInterface as Engine, Register } from 'claude-code'
import type { BoardTask, Checks, HeldTask, Lane, PeerSession, Pull } from '../types'
import { CHECKS, LANES as LANE_STYLES, ROW_HEIGHT, SP, alt, glyphs, laneIcon, laneOf, paneSvg, progress, ratio, rowSvg, subline, termBar } from './draw'
import type { Glyphs } from './draw'

const PANE = 'starpulse-board'
const SESSIONS = 'starpulse-sessions'
const KANBAN = 'starpulse-kanban'

const tasks = atom({ plugin: 'starpulse-board', key: 'tasks' } as const, null)
const sessions = atom({ plugin: 'starpulse-board', key: 'sessions' } as const, [])
const isHidden = atom({ plugin: 'starpulse-board', key: 'isHidden' } as const, false)
const openTask = atom({ plugin: 'starpulse-board', key: 'openTask' } as const, null)
const lanes = atom({ plugin: 'starpulse-board', key: 'lanes' } as const, null)
const folded = atom({ plugin: 'starpulse-board', key: 'folded' } as const, ['ready', 'waiting'])
const pickedTask = atom({ plugin: 'starpulse-board', key: 'pickedTask' } as const, null)

// A task as `starpulse board` prints it. An older starpulse leaves out the criteria, the reason and each PR's checks.
type RawTask = {
  id: string
  title: string
  assignee?: string
  holder?: string
  moves?: Record<string, unknown>
  waiting_on?: string[]
  criteria?: { text: string; checked?: boolean }[]
  pause_reason?: string
  prs?: { url: string; number?: number; checks?: string; merged?: boolean }[]
}
type Board = { columns: { state: string; name: string; tasks: RawTask[] }[] }

const CHECK_NAMES: Record<string, Checks> = { pass: 'pass', pending: 'pending', failing: 'fail' }

// The PR the row draws: the newest one still open, else the newest.
const pullOf = (prs: RawTask['prs']): Pull | null => {
  const open = (prs ?? []).filter(pr => !pr.merged)
  const pr = open.at(-1) ?? prs?.at(-1)
  const parsed = pr?.url.match(/github\.com\/([^/]+\/[^/]+)\/pull\/(\d+)/)
  const repo = parsed?.[1]
  const number = pr?.number ?? Number(parsed?.[2])
  if (!pr || !repo || !number) {
    return null
  }

  return { repo, number, checks: CHECK_NAMES[pr.checks ?? ''] ?? 'none' }
}

const taskOf = (t: RawTask, c: Board['columns'][number]): HeldTask => ({
  id: t.id,
  title: t.title,
  column: c.name,
  lane: c.state,
  holder: t.holder ?? '',
  criteria: t.criteria ?? null,
  reason: t.pause_reason ?? '',
  waitingOn: t.waiting_on ?? [],
  pull: pullOf(t.prs),
})

const heldOf = (board: Board): HeldTask[] => board.columns.flatMap(c => c.tasks.map(t => taskOf(t, c)))

// The Board as `starpulse board` prints it, narrowed by `filters`; null when it cannot be read.
const readBoard = async ($: Engine, filters: string[]): Promise<Board | null> => {
  try {
    const args = ['board', ...filters]
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

    return JSON.parse(ran.stdout) as Board
  } catch {
    return null
  }
}

// The tasks this session last claimed, from the StarPulse server `starpulse board` reads; null when it cannot be read.
const held = async ($: Engine): Promise<HeldTask[] | null> => {
  const session = await $.session.id().catch(() => null)
  const board = session === null ? null : await readBoard($, ['--holder', session])

  return board && heldOf(board)
}

// The Board tab's lanes, in the order work moves through them; New, Done and Archived stay off it.
const LANES = ['in_progress', 'review', 'needs_attention', 'ready', 'waiting']

// The open lanes of the whole Board, each task with the columns it may move to; empty when the Board cannot be read.
const readLanes = async ($: Engine): Promise<Lane[]> => {
  const board = await readBoard($, [])
  const columns = board?.columns ?? []
  const names = new Map(columns.map(c => [c.state, c.name]))
  const task = (t: RawTask, c: Board['columns'][number]): BoardTask => ({
    ...taskOf(t, c),
    assignee: t.assignee ?? '',
    moves: Object.keys(t.moves ?? {}).map(to => ({ to, name: names.get(to) ?? to })),
  })

  return LANES.flatMap(state => columns.filter(c => c.state === state)).map(c => ({ state: c.state, name: c.name, tasks: c.tasks.map(t => task(t, c)) }))
}

type Registered = { sessionId: string; pid: number; name?: string; status?: string; kind?: string }

// Each tmux pane's pid and the tmux session it sits in; empty when no tmux server runs.
const tmuxPanes = async ($: Engine): Promise<Map<number, string>> => {
  const panes = new Map<number, string>()
  const ran = await $.process.run(['tmux', 'list-panes', '-a', '-F', '#{pane_pid} #{session_name}']).catch(() => null)
  if (ran?.exitCode !== 0) {
    return panes
  }
  for (const row of ran.stdout.split('\n')) {
    const [pid, ...name] = row.split(' ')
    if (name.length) {
      panes.set(Number(pid), name.join(' '))
    }
  }

  return panes
}

// The host's other sessions, from the registry every Claude Code session writes under ~/.claude/sessions. A session
// StarPulse started runs as its tmux pane's own process, so its pid finds the tmux session to switch to.
const peers = async ($: Engine): Promise<PeerSession[]> => {
  try {
    const dir = `${await $.env.get('HOME')}/.claude/sessions`
    const own = await $.session.id()
    const [entries, panes] = await Promise.all([$.fs.list(dir), tmuxPanes($)])
    const files = entries.filter(f => f.name.endsWith('.json'))
    // A session that exits between the listing and the read is skipped, not fatal.
    const found = await Promise.all(
      files.map(f =>
        $.fs
          .read(`${dir}/${f.name}`)
          .then(text => JSON.parse(String(text)) as Registered)
          .catch(() => null),
      ),
    )
    const others = found.filter((s): s is Registered => s !== null && s.sessionId !== own)

    return others
      .map(s => {
        const tmux = panes.get(s.pid) ?? null
        return {
          id: s.sessionId,
          label: tmux ?? s.name ?? s.sessionId.slice(0, 8),
          status: s.status ?? 'unknown',
          tmux,
          isBackground: s.kind === 'bg',
        }
      })
      .sort((a, b) => a.label.localeCompare(b.label))
  } catch {
    return []
  }
}

const reloadLanes = async ($: Engine) => {
  const found = await readLanes($)
  await update($, lanes, () => found)
}

// Waits before starting a child that ended again: a second after one that printed, doubling to half a minute while none does.
const retryMs = (tries: number) => Math.min(1000 * 2 ** tries, 30_000)

// Runs `argv` for as long as it lives, handing `line` each line it prints, and starts it again once it ends.
const follow = async ($: Engine, argv: string[], input: string | undefined, line: (text: string) => unknown, tries = 0) => {
  let rest = ''
  let hasPrinted = false
  try {
    for await (const chunk of $.process.spawn({ argv, input })) {
      if (chunk.stream !== 'stdout') {
        continue
      }
      const lines = (rest + chunk.text).split('\n')
      rest = lines.pop() ?? ''
      for (const text of lines) {
        hasPrinted = true
        await line(text)
      }
    }
  } catch {
    // A child that cannot start, or a line that cannot be read, ends this run like an exit.
  }
  const next = hasPrinted ? 0 : tries
  $.clock.after(retryMs(next), () => follow($, argv, input, line, next + 1))
}

// Reads an event stream line by line, handing `frame` each event's name and data.
const events = (frame: (event: string, data: string) => unknown) => {
  let event = ''
  let data: string[] = []
  return async (line: string) => {
    if (line === '') {
      const [name, text] = [event, data.join('\n')]
      ;[event, data] = ['', []]
      if (text) {
        await frame(name, text)
      }
    } else if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      data.push(line.slice(5).replace(/^ /, ''))
    }
  }
}

// The server sends this session's held tasks once and again whenever they change; nothing here asks it twice.
const followHeld = async ($: Engine) => {
  const session = await $.session.id()
  const token = await $.env.get('STARPULSE_TOKEN')
  const server = ((await $.env.get('STARPULSE_URL')) || 'http://localhost:8766').replace(/\/$/, '')
  // The token goes in on stdin: every process on the host can read a child's argv.
  const auth = token ? ['-H', '@-'] : []
  const argv = ['curl', '-sfN', ...auth, `${server}/api/held?holder=${encodeURIComponent(session)}`]
  const onFrame = async (event: string, data: string) => {
    if (event === 'held') {
      await update($, tasks, () => heldOf(JSON.parse(data) as Board))
    }
  }

  await follow($, argv, token ? `Authorization: Bearer ${token}\n` : undefined, events(onFrame))
}

let hasOpened = false
let isStarting = true
const listPeers = async ($: Engine) => {
  const others = await peers($)
  await update($, sessions, () => others)
  // The first list opens the pane unasked; opened after Files, it is the dock tab on show, and the prompt keeps the keys.
  if (!hasOpened && others.length) {
    hasOpened = true
    await $.ui.open({ id: SESSIONS, title: 'Sessions' })
  }
}

// Rereads the registry without holding up the watch, one read at a time, rereading once if a change came in during it.
let reading: Promise<unknown> | null = null
let isStale = false
const listPeersSoon = ($: Engine) => {
  if (reading) {
    isStale = true
    return
  }
  reading = listPeers($).finally(() => {
    reading = null
    if (isStale) {
      isStale = false
      listPeersSoon($)
    }
  })
}

// Each write to the registry (a session starting, ending, or going busy or idle) rereads it.
const followPeers = async ($: Engine) => {
  const dir = `${await $.env.get('HOME')}/.claude/sessions`
  const argv = ['inotifywait', '-mq', '-e', 'create,delete,modify,moved_to,moved_from', '--format', '%f', dir]

  await follow($, argv, undefined, () => listPeersSoon($))
}

const tmux = ($: Engine, ...args: string[]) => $.process.run(['tmux', ...args]).catch(() => null)

// A session in a tmux pane is switched to. A background session has no pane, so it is first opened with `claude attach`
// in a tmux session of its own (-A reuses one already open). `claude attach` takes the job id, the session id's first 8
// characters (~/.claude/jobs/<job>), and refuses the full id. Fails visibly: switch-client needs this session's own
// terminal to be a tmux client.
const switchTo = async ($: Engine, s: PeerSession) => {
  let target = s.tmux
  if (target === null) {
    const job = s.id.slice(0, 8)
    target = `bg-${job}`
    const opened = await tmux($, 'new-session', '-A', '-d', '-s', target, 'claude', 'attach', job)
    if (opened?.exitCode !== 0) {
      $.ui.toast(`Cannot open ${s.label} in tmux: is tmux installed?`)
      return
    }
  }
  const ran = await tmux($, 'switch-client', '-t', target)
  if (ran?.exitCode !== 0) {
    $.ui.toast(`Cannot switch to ${s.label}: start Claude inside tmux to switch sessions`)
  }
}

// The Board tab opens with the keys and the whole Board read fresh.
const openBoard = async ($: Engine) => {
  await $.ui.open({ id: KANBAN, title: 'Board', focus: true })
  await reloadLanes($)
}

// A write to the StarPulse server `starpulse board` reads: null when it took, else the reason it was refused.
const post = async ($: Engine, path: string, body: object): Promise<string | null> => {
  const server = ((await $.env.get('STARPULSE_URL')) || 'http://localhost:8766').replace(/\/+$/, '')
  const argv = ['curl', '-sS', '-X', 'POST', '-H', 'Content-Type: application/json', '--data', JSON.stringify(body)]
  const ran = await $.process.run([...argv, '-w', '\n%{http_code}', `${server}${path}`]).catch(() => null)
  if (ran?.exitCode !== 0) {
    return `Cannot reach StarPulse at ${server}`
  }
  const lines = ran.stdout.trimEnd().split('\n')
  const code = lines.pop()
  if (code === '200') {
    return null
  }
  try {
    return (JSON.parse(lines.join('\n')) as { error?: string }).error ?? `StarPulse answered ${code}`
  } catch {
    return `StarPulse answered ${code}`
  }
}

// A lane whose task StarPulse can start a session for; any other task already has one to go to.
const STARTABLE = new Set(['ready', 'waiting', 'needs_attention'])

// StarPulse starts a task's session in tmux session task-<n>; a task already in progress is switched to where it runs.
const toSession = async ($: Engine, t: BoardTask, lane: string) => {
  const name = t.id.toLowerCase()
  if (!STARTABLE.has(lane)) {
    const others = await read($, sessions)
    const live = others.find(s => s.id === t.holder) ?? others.find(s => s.tmux === name)
    if (live) {
      await switchTo($, live)
    } else {
      $.ui.toast(`${t.id} has no live session`)
    }
    return
  }
  const refused = await post($, '/api/start', { task: t.id, assignee: t.assignee, harness: 'claude' })
  if (refused) {
    $.ui.toast(refused)
    return
  }
  const ran = await tmux($, 'switch-client', '-t', name)
  if (ran?.exitCode !== 0) {
    $.ui.toast(`Started ${t.id}: tmux attach -t ${name}`)
  }
  await reloadLanes($)
}

const moveTask = async ($: Engine, id: string, to: string) => {
  const refused = await post($, '/api/move', { task: id, to })
  if (refused) {
    $.ui.toast(refused)
  }
  await reloadLanes($)
}

const peerLine = (s: PeerSession) => `${s.status === 'busy' ? '●' : '○'} ${s.label} ${s.status}`

// The sessions that are working and the rest, which the band counts on one line.
const tally = (others: PeerSession[]) => {
  const working = others.filter(s => s.status === 'busy').length

  return { working, idle: others.length - working }
}

const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n))

// Pixels a monospace cell takes on the remote surfaces, and the room the Details and ✕ buttons beside the Svg row need.
const CELL_PX = 7.5
const BUTTONS_PX = 104

type Terminal = ElementTable<'terminal'>
// Every surface but the terminal draws the Svg; the desktop's table stands for them (Box, Text and Button are the same).
type Remote = ElementTable<'desktop'>

// The eighth-block bar as two Texts: the filled cells in `color`, the empty track dim.
const barTexts = (Text: Terminal['Text'], k: number, n: number, cells: number, color: string) => {
  const [fill, track] = termBar(k, n, cells)

  return [fill && <Text color={color}>{fill}</Text>, track && <Text color={SP.track}>{track}</Text>]
}

// The terminal's row as Ink draws it: lane icon, ID, title cut to fit, bar and count, lane, PR and its checks.
const termRow = (Box: Terminal['Box'], Text: Terminal['Text'], t: HeldTask, g: Glyphs) => {
  const [laneName, color] = laneOf(t)
  const p = progress(t)
  const sub = subline(t)
  const checks = t.pull ? CHECKS[t.pull.checks] : null

  return (
    <Box flexGrow={1} flexShrink={1} gap={1}>
      <Text color={color}>{laneIcon(g, t.lane)}</Text>
      <Text bold color={SP.ink}>
        {t.id}
      </Text>
      <Box flexGrow={1} flexShrink={1}>
        <Text wrap="truncate-end" color={sub.color}>
          {sub.text}
        </Text>
      </Box>
      {p && p.k !== null && <Box>{barTexts(Text, p.k, p.n, 12, color)}</Box>}
      {p && <Text color={SP.ink}>{ratio(p)}</Text>}
      <Text color={color}>{laneName}</Text>
      {t.pull && checks && (
        <Box gap={1}>
          <Text color={SP.muted}>{`#${t.pull.number}`}</Text>
          <Box key={`checks-${t.id}`}>
            <Text color={checks.color}>{g(t.pull.checks)}</Text>
          </Box>
        </Box>
      )}
    </Box>
  )
}

// The terminal's pane: the same facts as the Svg pane, one Text a line.
const termPane = (Box: Terminal['Box'], Text: Terminal['Text'], t: HeldTask, g: Glyphs) => {
  const [laneName, color] = laneOf(t)
  const p = progress(t)
  const checks = t.pull ? CHECKS[t.pull.checks] : null

  return (
    <Box flexDirection="column">
      <Text bold>{t.id}</Text>
      <Text>{t.title}</Text>
      <Box>
        <Text color={color}>{laneName}</Text>
        {t.holder && <Text dimColor>{` · held by ${t.holder}`}</Text>}
      </Box>
      {t.reason && <Text color={t.lane === 'needs_attention' ? SP.failText : undefined}>{t.reason}</Text>}
      {t.lane === 'waiting' && t.waitingOn.length > 0 && <Text dimColor>{`Waiting on ${t.waitingOn.join(' · ')}`}</Text>}
      {p && <Text dimColor>{`Acceptance criteria ${p.k === null ? p.n : `${p.k}/${p.n}`}`}</Text>}
      {(t.criteria ?? []).map(c => (
        <Text dimColor={c.checked === true}>{`${c.checked === true ? '✓' : c.checked === false ? '○' : '·'} ${c.text}`}</Text>
      ))}
      {t.pull && checks && (
        <Box gap={1}>
          <Text color={checks.color}>{g(t.pull.checks)}</Text>
          <Text>{`${t.pull.repo}#${t.pull.number}`}</Text>
          <Text dimColor>{checks.phrase}</Text>
        </Box>
      )}
    </Box>
  )
}

// The room a Board row leaves its title, in cells: the indent, the ID, a space either side of the title, the bar (four
// cells and its space) and the PR icon. One cell is left spare so a row never wraps.
const BAR_CELLS = 4
const titleRoom = (cols: number, idWidth: number, hasBar: boolean) => cols - (idWidth + 8 + (hasBar ? BAR_CELLS + 1 : 0)) - 1

// A title cut to `room` cells with an ellipsis, and the blanks that pad a short one to it.
const cut = (text: string, room: number): [shown: string, pad: string] => {
  const chars = [...text]
  if (chars.length <= room) {
    return [text, ' '.repeat(room - chars.length)]
  }

  return [`${chars.slice(0, Math.max(0, room - 1)).join('')}…`, '']
}

const toggle = async ($: Engine, id: string) => {
  if ((await read($, openTask)) === id) {
    await update($, openTask, () => null)
    await $.ui.close({ id: PANE })
  } else {
    await update($, openTask, () => id)
    await $.ui.open({ id: PANE, title: id })
  }
}

export const register: Register = (on, options) => {
  const g = glyphs(options.glyphs)

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'board', description: 'List the Board tasks this session holds' })
    await $.command.register({ name: 'kanban', description: 'Open the Board as a tab beside Files' })
    listPeersSoon($)
    void followPeers($)
    void followHeld($)

    return next(e)
  })

  on('command.run', { command: 'board' }, async $ => {
    await update($, isHidden, () => false)
    const found = await held($)
    await update($, tasks, () => found)
    if (found === null) {
      return { text: '`starpulse board` failed: is the StarPulse server running?' }
    }

    return {
      text: found.length ? found.map(t => `${t.id} [${t.column}] ${t.title}`).join('\n') : 'This session holds no tasks.',
    }
  })

  on('command.run', { command: 'kanban' }, async $ => {
    await openBoard($)

    return { text: 'Opened the Board tab.' }
  })

  // Until the first prompt, the first pane another plugin opens (Files) would take the dock's shown tab: reopen Sessions over it, once.
  on('ui.open', async ($, e, next) => {
    const result = await next(e)
    if (isStarting && hasOpened && e.id !== SESSIONS && e.id !== PANE && e.id !== KANBAN) {
      isStarting = false
      // Opening an open pane only retitles it: close it first so the open lands as the newest tab.
      $.clock.after(0, async () => {
        await $.ui.close({ id: SESSIONS })
        await $.ui.open({ id: SESSIONS, title: 'Sessions' })
      })
    }

    return result
  })

  on('prompt.submit', ($, e, next) => {
    isStarting = false

    return next(e)
  })

  on('ui.close', { id: PANE }, async ($, e, next) => {
    await update($, openTask, () => null)

    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const found = (await read($, tasks)) ?? []
    const others = await read($, sessions)
    if (e.props.hasSurvey || (!found.length && !others.length)) {
      return next(e)
    }

    const { Box, Button, Text, Svg } = $.ui.resolve(e) as Remote
    if (await read($, isHidden)) {
      const label = found.length ? 'Show task' : 'Show sessions'
      return (
        <Button key="show" label={label} plain onPress={() => update($, isHidden, () => false)}>
          <Text color={SP.slate}>{label}</Text>
        </Button>
      )
    }
    const hide = (
      <Button key="hide" label="✕" plain onPress={() => update($, isHidden, () => true)}>
        <Text color={SP.faint}>✕</Text>
      </Button>
    )

    const opened = await read($, openTask)
    const width = clamp(Math.floor(e.props.bodyColumns * CELL_PX) - BUTTONS_PX, 280, 860)
    const { working, idle } = tally(others)

    return (
      <Box flexDirection="column">
        {found.map((t, i) => {
          const label = opened === t.id ? 'Close' : 'Details'

          return (
            <Box flexDirection="row" alignItems="center" gap={1}>
              {e.surface === 'terminal' ? (
                termRow(Box, Text, t, g)
              ) : (
                <Svg source={rowSvg(t, width)} alt={alt(t)} width={width} height={ROW_HEIGHT} />
              )}
              <Button key={`details-${t.id}`} label={label} plain onPress={() => toggle($, t.id)}>
                <Text color={SP.slate}>{`[${label}]`}</Text>
              </Button>
              {i === 0 && hide}
            </Box>
          )
        })}
        <Box flexDirection="row" alignItems="center" gap={2}>
          {others.length > 0 && (
            <Button
              key="sessions"
              label={`${working} working · ${idle} idle`}
              plain
              onPress={() => $.ui.open({ id: SESSIONS, title: 'Sessions', focus: true })}
            >
              <Text color={SP.run}>{`${g('working')} ${working} working`}</Text>
              {'  '}
              <Text color={SP.slate}>{`${g('idle')} ${idle} idle`}</Text>
            </Button>
          )}
          {others.length > 0 && <Text color={SP.faint}>·</Text>}
          <Button key="kanban" label="Board" plain onPress={() => openBoard($)}>
            <Text color={SP.agent}>{`${g('board')} Board`}</Text>
          </Button>
          {!found.length && hide}
        </Box>
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e, next) => {
    const found = await read($, tasks)
    const picked = await read($, openTask)
    const t = found?.find(x => x.id === picked) ?? found?.[0]
    if (!t) {
      return next(e)
    }

    const { Box, Text, Svg } = $.ui.resolve(e) as Remote
    if (e.surface !== 'terminal') {
      const width = clamp(Math.floor(e.props.bodyColumns * CELL_PX), 240, 720)
      const { source, height } = paneSvg(t, width)

      return <Svg source={source} alt={`${alt(t)}. ${t.title}`} width={width} height={height} />
    }

    return termPane(Box, Text, t, g)
  })

  on('ui.render', { component: 'Pane', requestId: KANBAN }, async ($, e) => {
    if (e.surface === 'terminal' && e.props.placement === 'inline') {
      void $.ui.close({ id: KANBAN }).catch(() => undefined)
      const { Box } = $.ui.resolve(e)
      return <Box />
    }
    const found = await read($, lanes)
    const shut = await read($, folded)
    const picked = await read($, pickedTask)
    const others = await read($, sessions)
    const { Box, Button, Text } = $.ui.resolve(e) as Remote
    if (found === null || !found.length) {
      return <Text dimColor>{found === null ? 'Reading the Board…' : '`starpulse board` failed: is the StarPulse server running?'}</Text>
    }
    const fold = (state: string) => update($, folded, f => (f.includes(state) ? f.filter(x => x !== state) : [...f, state]))
    const cols = e.props.bodyColumns
    const open = found.reduce((sum, l) => sum + l.tasks.length, 0)
    const idWidth = Math.max(...found.flatMap(l => l.tasks.map(t => t.id.length)), 0)
    // The bar goes first when the dock is too narrow to leave a title any room.
    const hasBar = titleRoom(cols, idWidth, true) >= 6
    const room = Math.max(0, titleRoom(cols, idWidth, hasBar))

    const row = (t: BoardTask, color: string, isPicked: boolean) => {
      const p = progress(t)
      const sub = subline(t)
      const [shown, pad] = cut(sub.text, room)
      const checks = t.pull ? CHECKS[t.pull.checks] : null
      const [fill, track] = p && p.k !== null ? termBar(p.k, p.n, BAR_CELLS) : ['', ' '.repeat(BAR_CELLS)]

      return (
        <Button key={`task:${t.id}`} label={`${t.id} ${t.title}`} plain onPress={() => update($, pickedTask, x => (x === t.id ? null : t.id))}>
          {'  '}
          <Text bold={isPicked} color={isPicked ? color : SP.slate}>
            {t.id}
          </Text>
          {' '}
          <Text color={sub.color}>{shown}</Text>
          {pad}
          {hasBar && ' '}
          {hasBar && fill && <Text color={p?.k === p?.n ? SP.ok : color}>{fill}</Text>}
          {hasBar && <Text color={SP.track}>{track}</Text>}
          {' '}
          {checks && t.pull ? <Text color={checks.color}>{g(t.pull.checks)}</Text> : ' '}
        </Button>
      )
    }

    const detail = (t: BoardTask, state: string) => {
      const p = progress(t)
      const isStartable = STARTABLE.has(state)
      const holder = others.find(s => s.id === t.holder)?.label ?? t.holder.slice(0, 8)
      const checks = t.pull ? CHECKS[t.pull.checks] : null
      const facts = [
        t.holder && (
          <Box key="holder">
            <Text color={SP.muted}>held by </Text>
            <Text color={SP.slate}>{holder}</Text>
          </Box>
        ),
        p && (
          <Text key="criteria" color={p.k === p.n ? SP.ok : SP.muted}>
            {p.k === null ? ratio(p) : `${ratio(p)} criteria`}
          </Text>
        ),
        t.pull && checks && (
          <Box key="pr" gap={1}>
            <Text color={SP.agent}>{`${g('pr')} #${t.pull.number}`}</Text>
            <Text color={checks.color}>{checks.phrase}</Text>
          </Box>
        ),
      ].filter(Boolean)

      return (
        <Box key={`detail-${t.id}`} flexDirection="column" paddingLeft={4}>
          <Text bold color={SP.ink}>
            {t.title}
          </Text>
          {facts.length > 0 && (
            <Box flexWrap="wrap" columnGap={1}>
              {facts.flatMap((fact, i) => (i ? [<Text key={`sep-${i}`} color={SP.faint}>·</Text>, fact] : [fact]))}
            </Box>
          )}
          {t.reason && <Text color={SP.failText}>{t.reason}</Text>}
          <Box flexWrap="wrap" columnGap={2}>
            <Button key={`session:${t.id}`} label={isStartable ? 'Start session' : 'Go to session'} plain onPress={() => toSession($, t, state)}>
              <Text bold color={SP.ok}>{`${g(isStartable ? 'start' : 'go')} ${isStartable ? 'Start session' : 'Go to session'}`}</Text>
            </Button>
            {t.moves.map(m => (
              <Button key={`move:${t.id}:${m.to}`} label={`→ ${m.name}`} plain onPress={() => moveTask($, t.id, m.to)}>
                <Text color={LANE_STYLES[m.to]?.[1] ?? SP.slate}>{`${g('move')} ${LANE_STYLES[m.to]?.[0] ?? m.name}`}</Text>
              </Button>
            ))}
          </Box>
        </Box>
      )
    }

    // The dock paints grey behind every cell a pane draws; the root fills black to cover it.
    return (
      <Box flexDirection="column" flexGrow={1} backgroundColor={SP.black}>
        <Box>
          <Text bold color={SP.agent}>{`${g('board')} Board`}</Text>
          <Text color={SP.muted}>{` · ${open} open`}</Text>
          <Box flexGrow={1} />
          <Button key="refresh" label="Refresh" plain onPress={() => reloadLanes($)}>
            <Text color={SP.faint}>{g('refresh')}</Text>
          </Button>
        </Box>
        {found.map(l => {
          const isFolded = shut.includes(l.state)
          const [laneName, color] = LANE_STYLES[l.state] ?? [l.name, SP.slate]
          const header = `${laneName.toUpperCase()} ${l.tasks.length}`

          return (
            <Box key={`lane-${l.state}`} flexDirection="column" marginTop={1}>
              <Box>
                <Button key={`lane:${l.state}`} label={`${isFolded ? '▸' : '▾'} ${l.name} ${l.tasks.length}`} plain onPress={() => fold(l.state)}>
                  <Text color={SP.faint}>{g(isFolded ? 'right' : 'down')}</Text>
                  {' '}
                  <Text color={color}>{laneIcon(g, l.state)}</Text>
                  {' '}
                  <Text bold color={color}>
                    {laneName.toUpperCase()}
                  </Text>
                  {' '}
                  <Text color={SP.muted}>{String(l.tasks.length)}</Text>
                </Button>
                <Text color={SP.track}>{` ${'─'.repeat(Math.max(0, cols - header.length - 6))}`}</Text>
              </Box>
              {!isFolded &&
                l.tasks.map(t => (
                  <Box key={`row-${t.id}`} flexDirection="column">
                    {row(t, color, picked === t.id)}
                    {picked === t.id && detail(t, l.state)}
                  </Box>
                ))}
            </Box>
          )
        })}
        <Box marginTop={1}>
          <Text color={SP.faint}>↑↓ move · ↵ pick · lane header folds</Text>
        </Box>
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: SESSIONS }, async ($, e, next) => {
    // Outside the fullscreen layout the terminal places a pane inline above the prompt; like Files, Sessions shows only in the dock.
    if (e.surface === 'terminal' && e.props.placement === 'inline') {
      void $.ui.close({ id: SESSIONS }).catch(() => undefined)
      const { Box } = $.ui.resolve(e)
      return <Box />
    }
    const others = await read($, sessions)
    if (!others.length) {
      return next(e)
    }

    const { Box, Button, Text } = $.ui.resolve(e) as Remote

    return (
      <Box flexDirection="column">
        {others.map(s =>
          s.tmux !== null || s.isBackground ? (
            <Button key={`session:${s.id}`} label={peerLine(s)} onPress={() => switchTo($, s)} />
          ) : (
            <Text key={`peer:${s.id}`} dimColor>
              {peerLine(s)}
            </Text>
          ),
        )}
      </Box>
    )
  })
}
