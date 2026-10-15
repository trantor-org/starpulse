# starpulse-board

Draws the Board tasks a Claude Code session holds above the prompt, a Board pane (`/kanban`) and a Sessions pane, in
the terminal CLI only: on Claude Desktop and mobile it draws nothing and opens no dock.
Install with `/plugin install starpulse-board@starpulse`; the StarPulse CLI reference (`docs/cli.md`) documents the
band and the Board pane.

At session start the dock opens without taking the keys: Sessions when another session runs, then the Board, the tab on
show.

## Sessions pane

Lists the Claude Code sessions in `~/.claude/sessions/` it can switch to in two groups, Active and Archived (Archived
folded by default; each header folds). Active holds working and idle sessions together, told apart by the status icon
(`●` working, `○` idle). A live session is listed only when it runs in a tmux pane, plus this session; a background or
desktop session has none, so it is left out. A row shows the status icon, name, a `you` marker on this session, the held
task as a lane-coloured chip, the age and an archive icon.

| Key | Action |
| --- | --- |
| `n` | New session: a tmux session `claude-NNNNNN` running `claude` in the workspace, switched to |
| `f` | Focus the filter: text over name, tmux session and task |
| `a` | Archive the row focused with ↑↓ |
| chips | working, idle, archived; toggle, several combine as OR, and with the text as AND |

Archive kills the row's tmux session and moves the row to Archived. When the row is this session, a fresh tmux
session is created and switched to first; if that fails the session is kept and a toast says so.

Archived rows persist in `$.store` as `{ sessionId, name, cwd, task, archivedAt }`. Pressing one, or `a` on it, runs
`claude --resume <sessionId>` in a new tmux session at the recorded `cwd`.

A Remote Control session archived in claude.ai shows in Archived too: its registry record has lost `bridgeSessionId`
while its transcript holds a `bridge-session` row. Its process still runs, so pressing it switches to its tmux session
and `a` archives it here.

Options: `glyphs` is `nerd` (default) or `plain`.

## Black dock

Both panes fill their body black. The dock's tab strip, left border and bottom row are Claude Code's
`composerSidebarBackground` (grey in the dark theme), which no pane draws. The plugin ships the theme
`themes/black-dock.json`, the dark theme with that key black; select it with
`"theme": "custom:starpulse-board:black-dock"` in `~/.claude/settings.json`.
