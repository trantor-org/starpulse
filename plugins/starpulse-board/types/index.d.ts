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
 * Another Claude Code session on this host: its id, label and registry status, the tmux session holding it if any,
 * and whether it is a background (`claude --bg`) session, which `claude attach` opens in a terminal.
 */
export type PeerSession = { id: string; label: string; status: string; tmux: string | null; isBackground: boolean }

declare module 'claude-code' {
  interface PluginState {
    'starpulse-board': { tasks: HeldTask[] | null; sessions: PeerSession[]; isHidden: boolean; openTask: string | null }
  }
}
