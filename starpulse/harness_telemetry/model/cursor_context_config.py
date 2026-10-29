"""The `[cursor_context]` config table: how much context a Cursor task session may use before it is reset.

Cursor has no client-side compaction threshold, so StarPulse enforces one from outside: it reads each Cursor session's
context use from the agent's pane footer (a percent of the model's window) and, once a session is past `limit_tokens`,
asks it to checkpoint its working doc, then ends it and starts a fresh session on the same task.

- `limit_tokens`: context tokens past which a session is reset (default 150000).
- `window_tokens`: the context window the footer's percent is read against (default 200000); one value for every
  model, because the footer names no window.
- `wrapup_s`: seconds a session is given to checkpoint after it is asked, before it is reset even if still busy
  (default 600).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CursorContext", "CursorContextError", "parse_cursor_context"]

_KEYS = {"limit_tokens", "window_tokens", "wrapup_s"}


class CursorContextError(ValueError):
    """The table cannot be read; the message names the key to fix."""


@dataclass(frozen=True)
class CursorContext:
    limit_tokens: int = 150_000
    """Context tokens past which a Cursor task session is checkpointed and restarted."""
    window_tokens: int = 200_000
    """The context window the pane footer's percent is read against."""
    wrapup_s: float = 600.0
    """Seconds an asked session has to checkpoint before it is restarted regardless."""


def _tokens(raw: dict[str, object], key: str, default: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CursorContextError(f"cursor_context: {key} must be a positive whole number")
    return value


def parse_cursor_context(raw: object) -> CursorContext:
    """The `[cursor_context]` table, or the default one for `None`; each refusal names the key to fix."""
    if raw is None:
        return CursorContext()
    if not isinstance(raw, dict):
        raise CursorContextError("cursor_context must be a [cursor_context] table")
    if unknown := sorted(raw.keys() - _KEYS):
        raise CursorContextError(
            f"cursor_context: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_KEYS))}"
        )
    defaults = CursorContext()
    limit = _tokens(raw, "limit_tokens", defaults.limit_tokens)
    window = _tokens(raw, "window_tokens", defaults.window_tokens)
    wrapup = raw.get("wrapup_s", defaults.wrapup_s)
    if isinstance(wrapup, bool) or not isinstance(wrapup, int | float) or wrapup <= 0:
        raise CursorContextError("cursor_context: wrapup_s must be a positive number of seconds")
    if limit > window:
        raise CursorContextError("cursor_context: limit_tokens must not exceed window_tokens")
    return CursorContext(limit, window, float(wrapup))
