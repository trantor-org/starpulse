/** What a pull request's checks roll up to; `none` when it has no required checks yet. */
export type Checks = 'pass' | 'pending' | 'fail' | 'none'

/** The pull request a task cites: its repository, number and checks. */
export type Pull = { repo: string; number: number; checks: Checks }

/** One acceptance criterion; `checked` is absent when the server cannot say. */
export type Criterion = { text: string; checked?: boolean }

/**
 * One task the session holds: its key, title, the name of the column it sits in and that column's lane id, plus what
 * the band draws of it. `criteria` is null when the server serves none (an older `starpulse`); `reason` is why a
 * Needs attention task waits on the operator, empty otherwise.
 */
export type HeldTask = {
  id: string
  title: string
  column: string
  lane: string
  holder: string
  criteria: Criterion[] | null
  reason: string
  waitingOn: string[]
  pull: Pull | null
}

/**
 * A Claude Code session on this host: its id, label (its tmux session, else its name) and registry status, the tmux
 * session holding it if any, and whether it is a background (`claude --bg`) session, which `claude attach` opens in a
 * terminal. `name` is what its row reads, `cwd` where it runs, `updatedAt` its registry timestamp in ms, and `isOwn`
 * marks the session this pane is drawn in.
 */
export type PeerSession = {
  id: string
  label: string
  name: string
  status: string
  tmux: string | null
  isBackground: boolean
  isOwn: boolean
  cwd: string
  updatedAt: number
}

/** A session the operator archived: kept in `$.store` so `claude --resume <sessionId>` can reopen it at `cwd`. */
export type ArchivedSession = { sessionId: string; name: string; cwd: string; task: string; archivedAt: number }

/** A column a task may move to: its state id and name. */
export type Move = { to: string; name: string }

/** A task the Board tab lists: what the band draws of a held task, plus its assignee and the columns it may move to. */
export type BoardTask = HeldTask & { assignee: string; moves: Move[] }

/** One open lane of the Board tab: its state id, name and tasks. */
export type Lane = { state: string; name: string; tasks: BoardTask[] }

declare module 'claude-code' {
  interface PluginState {
    'starpulse-board': {
      tasks: HeldTask[] | null
      sessions: PeerSession[]
      isHidden: boolean
      openTask: string | null
      lanes: Lane[] | null
      folded: string[]
      pickedTask: string | null
      archived: ArchivedSession[]
      query: string
      chips: string[]
      sessionFolds: string[]
      focused: string | null
    }
  }
}
