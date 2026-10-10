# Security

The page has no sign-in and listens on `127.0.0.1` only; `--host 0.0.0.0` exposes it to your network, which you do
only on a network you trust. A write is refused unless it is a JSON request with no `Origin` or this server's own, so
another site cannot write through your browser. `/api/move` is unauthenticated on the LAN: machine `writers` stop an
agent's accident, not an adversary.

`POST /api/pulls/refresh` is the exception: with `refresh_token_env` set it takes a bearer token and refuses a missing or
wrong one (401) and a repository the instance does not track (403). It only brings forward one read of a pull request the
instance already tracks, so the token guards GitHub's rate budget, not data.

The Claude Code receiver publishes which session moved, on which event and when; prompt, reply and tool text is
neither stored nor forwarded. For session health it also keeps, per Claude Code and Codex event, only counts, durations,
token counts, a model, effort, tool, skill or decision name, the branch, and the ref a shell `git switch` or
`git checkout` names, and for each tool call the activity it performed (a leading command name such as `git status`
or `ssh root@unraid`, never its arguments) and the file path a file tool read or wrote; it never reads a prompt, a
reply, a tool's output or an account field. These stay in the instance's own event log, and only a path under a
configured `[analytics]` root, cut to its first two components, is ever served. Forwarding to a hub
keeps `actor` and `assignee` at home unless the instance opts in.
A hub refuses to start without an `[oidc]` table. See [Run a hub](hub.md)
before exposing one.
