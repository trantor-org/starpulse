/** One task the session holds: its key, title and the name of the column it sits in. */
export type HeldTask = { id: string; title: string; column: string }

declare module 'claude-code' {
  interface PluginState {
    'starpulse-board': { tasks: HeldTask[] | null; isHidden: boolean }
  }
}
