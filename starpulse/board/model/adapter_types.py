"""The modules StarPulse ships, and the names a `[board]` or `[[runs]]` `type` resolves to.

This module imports nothing, so the config reads the table without importing an adapter. The table sits in the Board's
model because an engine's name belongs only inside an adapter's own module and the config must not import one.

A new tracker is one adapter module plus one `BUILT_IN` entry here.
"""

#: The board type a config without a `[board]` table names.
DEFAULT_TYPE = "native"

#: Built-in type -> module. A dotted type is a module path an installed package provides and is not listed.
BUILT_IN = {
    "native": "starpulse.board.adapters.native",
    "github_actions": "starpulse.runs.adapters.outbound.github_actions",
    "systemd": "starpulse.runs.adapters.outbound.systemd",
    "temporal": "starpulse.runs.adapters.outbound.temporal",
    "woodpecker": "starpulse.runs.adapters.outbound.woodpecker",
}

#: The run adapters' worker contexts. Each runs as a thread of `starpulse worker contexts`, or alone as `starpulse worker <context>`.
ADAPTER_CONTEXTS = ("github-actions", "systemd", "woodpecker")


def module_name(kind: str) -> str:
    """The module a `[board]` or `[[runs]]` type names: a dotted path as it is, a bare name through `BUILT_IN`."""
    if "." in kind:
        return kind
    if kind not in BUILT_IN:
        raise ValueError(f"no built-in adapter type {kind}; built-in types are {', '.join(sorted(BUILT_IN))}")
    return BUILT_IN[kind]
