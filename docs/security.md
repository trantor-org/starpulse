# Security

The page has no sign-in and listens on `127.0.0.1` only; `--host 0.0.0.0` exposes it to your network, which you do
only on a network you trust. A write is refused unless it is a JSON request with no `Origin` or this server's own, so
another site cannot write through your browser. `/api/move` is unauthenticated on the LAN: machine `writers` stop an
agent's accident, not an adversary.

The Claude Code receiver publishes which session moved, on which event and when; prompt, reply and tool text is
neither stored nor forwarded. For session health it also keeps, per Claude Code and Codex event, only counts, durations,
token counts, a model, effort, tool, skill or decision name, the branch, and the ref a shell `git switch` or
`git checkout` names; it never reads a prompt, a reply, a tool's output or an account field. Forwarding to a hub
keeps `actor` and `assignee` at home unless the instance opts in.
A hub refuses to start without an `[oidc]` table. See [Run a hub](hub.md)
before exposing one.
