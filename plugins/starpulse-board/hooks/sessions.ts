import type { ArchivedSession, Lane, PeerSession } from '../types'

// A row's status, drawn as its icon and filtered by its chip.
export type Status = 'working' | 'idle' | 'archived'

// Active holds the working and idle sessions together; their icons tell them apart.
export type Group = 'active' | 'archived'

export const GROUPS: [group: Group, name: string][] = [
  ['active', 'Active'],
  ['archived', 'Archived'],
]
export const CHIPS: Status[] = ['working', 'idle', 'archived']

// One line of the Sessions pane: a live session, or an archived one that `claude --resume` can reopen.
export type Row = {
  id: string
  name: string
  tmux: string | null
  cwd: string
  task: string
  lane: string
  status: Status
  isBackground: boolean
  isOwn: boolean
  updatedAt: number
  peer: PeerSession | null
}

export type Held = { task: string; title: string; lane: string }

// The task each session holds and the lane that task sits in, from the open lanes of the Board.
export const holdersOf = (found: Lane[] | null): Map<string, Held> => {
  const held = new Map<string, Held>()
  for (const lane of found ?? []) {
    for (const t of lane.tasks) {
      if (t.holder && !held.has(t.holder)) {
        held.set(t.holder, { task: t.id, title: t.title, lane: lane.state })
      }
    }
  }

  return held
}

// The lane each open task sits in; an archived row names its task but no lane of its own.
export const lanesOf = (found: Lane[] | null): Map<string, string> => {
  const byTask = new Map<string, string>()
  for (const lane of found ?? []) {
    for (const t of lane.tasks) {
      byTask.set(t.id, lane.state)
    }
  }

  return byTask
}

// The registry sessions that are not archived: an archived session's registry file lingers until it is reaped.
export const alive = (all: PeerSession[], archived: ArchivedSession[]) => {
  const gone = new Set(archived.map(a => a.sessionId))

  return all.filter(s => !gone.has(s.id))
}

export const groupOf = (r: Row): Group => (r.status === 'archived' ? 'archived' : 'active')

// Every row the pane can draw, before any filter: the live sessions it can switch to (each in a tmux pane, and this one),
// then the archived ones. A live session archived in claude.ai is archived too, but keeps its tmux session to switch to. A background or desktop session has no pane, so it is left out rather than listed unenterable.
export const rowsOf = (all: PeerSession[], archived: ArchivedSession[], held: Map<string, Held>, byTask: Map<string, string>): Row[] => {
  const enterable = alive(all, archived).filter(s => s.tmux !== null || s.isOwn)
  const live = enterable.map((s): Row => {
    const mine = held.get(s.id)
    // Claude titles a session StarPulse started from its start prompt, the task ID the chip already shows.
    const isTaskId = mine !== undefined && s.name === mine.task && mine.title !== ''

    return {
      id: s.id,
      name: isTaskId ? mine.title : s.name,
      tmux: s.tmux,
      cwd: s.cwd,
      task: mine?.task ?? '',
      lane: mine?.lane ?? '',
      status: s.isArchivedRemotely ? 'archived' : s.status === 'busy' ? 'working' : 'idle',
      isBackground: s.isBackground,
      isOwn: s.isOwn,
      updatedAt: s.updatedAt,
      peer: s,
    }
  })
  const kept = archived.map(
    (a): Row => ({
      id: a.sessionId,
      name: a.name,
      tmux: null,
      cwd: a.cwd,
      task: a.task,
      lane: byTask.get(a.task) ?? '',
      status: 'archived',
      isBackground: false,
      isOwn: false,
      updatedAt: a.archivedAt,
      peer: null,
    }),
  )

  return [...live, ...kept]
}

// A chip counts its rows whatever the filter says.
export const countOf = (rows: Row[], chip: Status) => rows.filter(r => r.status === chip).length

// The text matches a row's name, tmux session or task; the chips, if any are on, match when any of them does.
export const matches = (r: Row, query: string, chips: string[]) => {
  const text = query.trim().toLowerCase()
  const haystack = `${r.name} ${r.tmux ?? ''} ${r.task}`.toLowerCase()

  return haystack.includes(text) && (!chips.length || chips.includes(r.status))
}

// This session first, then the most recently active.
export const ordered = (rows: Row[]) => [...rows].sort((a, b) => Number(b.isOwn) - Number(a.isOwn) || b.updatedAt - a.updatedAt)

// How long ago, in the unit that fits: now, 5m, 3h, 2d.
export const ago = (now: number, then: number) => {
  const minutes = Math.max(0, Math.round((now - then) / 60_000))
  if (minutes < 1) {
    return 'now'
  }
  if (minutes < 60) {
    return `${minutes}m`
  }

  return minutes < 1440 ? `${Math.round(minutes / 60)}h` : `${Math.round(minutes / 1440)}d`
}

// What a row's button is named: its name, then each fact it draws.
export const rowLabel = (r: Row, age: string) =>
  [r.name, r.isOwn && 'you', r.task, r.isBackground && 'background', r.status, age].filter(Boolean).join(', ')

// The session id of a focused row's button (`session:<id>`, `archive:<id>`, `resume:<id>`).
export const focusedId = (key: string | null) => key?.match(/^(?:session|archive|resume):(.+)$/)?.[1] ?? null
