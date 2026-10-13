import { atom, read, update } from 'claude-code'
import type { ElementTable, EngineInterface as Engine, Register } from 'claude-code'
import type { Checks, HeldTask, PeerSession, Pull } from '../types'
import { CHECKS, ROW_HEIGHT, SP, alt, laneOf, paneSvg, progress, ratio, rowSvg, subline, termBar } from './draw'

const PANE = 'starpulse-board'
const SESSIONS = 'starpulse-sessions'

const tasks = atom({ plugin: 'starpulse-board', key: 'tasks' } as const, null)
const sessions = atom({ plugin: 'starpulse-board', key: 'sessions' } as const, [])
const isHidden = atom({ plugin: 'starpulse-board', key: 'isHidden' } as const, false)
const openTask = atom({ plugin: 'starpulse-board', key: 'openTask' } as const, null)

// A task as `starpulse board` prints it. An older starpulse leaves out the criteria, the reason and each PR's checks.
type RawTask = {
  id: string
  title: string
  holder?: string
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
  const number = pr?.number ?? Number(parsed?.[2])
  if (!pr || !parsed || !number) {
    return null
  }

  return { repo: parsed[1], number, checks: CHECK_NAMES[pr.checks ?? ''] ?? 'none' }
}

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

    return board.columns.flatMap(c =>
      c.tasks.map(t => ({
        id: t.id,
        title: t.title,
        column: c.name,
        lane: c.state,
        holder: t.holder ?? '',
        criteria: t.criteria ?? null,
        reason: t.pause_reason ?? '',
        waitingOn: t.waiting_on ?? [],
        pull: pullOf(t.prs),
      })),
    )
  } catch {
    return null
  }
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

let hasOpened = false
let isStarting = true
const refresh = async ($: Engine) => {
  // The session list is a local read; it draws without waiting on the slower board read.
  const listed = peers($).then(async others => {
    await update($, sessions, () => others)
    // The first list opens the pane unasked; opened after Files, it is the dock tab on show, and the prompt keeps the keys.
    if (!hasOpened && others.length) {
      hasOpened = true
      await $.ui.open({ id: SESSIONS, title: 'Sessions' })
    }
  })
  const found = await held($)
  await update($, tasks, () => found)
  await listed

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

const peerLine = (s: PeerSession) => `${s.status === 'busy' ? '●' : '○'} ${s.label} ${s.status}`

// Other sessions change on their own, so the band rereads the registry between this session's turns too.
const count = (others: PeerSession[]) => {
  const busy = others.filter(s => s.status === 'busy').length
  return `● ${busy} busy · ○ ${others.length - busy} idle`
}
const PEER_POLL_MS = 5000

const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n))

// Pixels a monospace cell takes on the remote surfaces, and the room the Details and ✕ buttons beside the Svg row need.
const CELL_PX = 7.5
const BUTTONS_PX = 104

type Terminal = ElementTable<'terminal'>
// Every surface but the terminal draws the Svg; the desktop's table stands for them (Box, Text and Button are the same).
type Remote = ElementTable<'desktop'>

// The terminal's row as Ink draws it: lane dot, ID, title cut to fit, bar and count, lane, PR and its checks.
const termRow = (Box: Terminal['Box'], Text: Terminal['Text'], t: HeldTask) => {
  const [laneName, color] = laneOf(t)
  const p = progress(t)
  const sub = subline(t)
  const checks = t.pull ? CHECKS[t.pull.checks] : null

  return (
    <Box flexGrow={1} flexShrink={1} gap={1}>
      <Text color={color}>●</Text>
      <Text bold>{t.id}</Text>
      <Box flexGrow={1} flexShrink={1}>
        <Text wrap="truncate-end" color={sub.color === SP.ink ? undefined : sub.color}>
          {sub.text}
        </Text>
      </Box>
      {p && p.k !== null && <Text color={color}>{termBar(p.k, p.n)}</Text>}
      {p && <Text>{ratio(p)}</Text>}
      <Text color={color}>{laneName}</Text>
      {t.pull && checks && (
        <Box gap={1}>
          <Text dimColor>{`#${t.pull.number}`}</Text>
          <Box key={`checks-${t.id}`}>
            <Text color={checks.color}>{checks.glyph}</Text>
          </Box>
        </Box>
      )}
    </Box>
  )
}

// The terminal's pane: the same facts as the Svg pane, one Text a line.
const termPane = (Box: Terminal['Box'], Text: Terminal['Text'], t: HeldTask) => {
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
          <Text color={checks.color}>{checks.glyph}</Text>
          <Text>{`${t.pull.repo}#${t.pull.number}`}</Text>
          <Text dimColor>{checks.phrase}</Text>
        </Box>
      )}
    </Box>
  )
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

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'board', description: 'List the Board tasks this session holds' })
    void refresh($)
    $.clock.every(PEER_POLL_MS, () => refreshSoon($))

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

  // Until the first prompt, the first pane another plugin opens (Files) would take the dock's shown tab: reopen Sessions over it, once.
  on('ui.open', async ($, e, next) => {
    const result = await next(e)
    if (isStarting && hasOpened && e.id !== SESSIONS && e.id !== PANE) {
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
      return <Button key="show" label={label} onPress={() => update($, isHidden, () => false)} />
    }
    const hide = <Button key="hide" label="✕" onPress={() => update($, isHidden, () => true)} />

    const opened = await read($, openTask)
    const width = clamp(Math.floor(e.props.bodyColumns * CELL_PX) - BUTTONS_PX, 280, 860)

    return (
      <Box flexDirection="column">
        {found.map((t, i) => (
          <Box flexDirection="row" alignItems="center" gap={1}>
            {e.surface === 'terminal' ? (
              termRow(Box, Text, t)
            ) : (
              <Svg source={rowSvg(t, width)} alt={alt(t)} width={width} height={ROW_HEIGHT} />
            )}
            <Button key={`details-${t.id}`} label={opened === t.id ? 'Close' : 'Details'} onPress={() => toggle($, t.id)} />
            {i === 0 && hide}
          </Box>
        ))}
        {others.length > 0 && (
          <Box flexDirection="row" alignItems="center" gap={1}>
            <Button key="sessions" label={count(others)} onPress={() => $.ui.open({ id: SESSIONS, title: 'Sessions', focus: true })} />
            {!found.length && hide}
          </Box>
        )}
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

    return termPane(Box, Text, t)
  })

  on('ui.render', { component: 'Pane', requestId: SESSIONS }, async ($, e, next) => {
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
