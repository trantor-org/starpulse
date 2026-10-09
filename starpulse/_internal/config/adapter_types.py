"""The adapters StarPulse ships, and the names a bare `[board]` or `[[runs]]` `type` resolves to.

This module imports nothing, so the config reads the table without importing an adapter. The table sits in `config`
because an engine's name belongs only inside an adapter's own module and the config must not import one.
"""

#: Built-in type -> module. A dotted type is a module path an installed package provides and is not listed.
BUILT_IN = {
    "native": "starpulse._internal.board.native",
    "upstream_backlog": "starpulse._internal.board.upstream_backlog",
    "jira": "starpulse._internal.board.jira",
    "dagu": "starpulse._internal.runs.dagu",
    "github_actions": "starpulse._internal.runs.github_actions",
    "systemd": "starpulse._internal.runs.systemd",
}


def module_name(kind: str) -> str:
    """The module a `[board]` or `[[runs]]` type names: a dotted path as it is, a bare name through `BUILT_IN`."""
    if "." in kind:
        return kind
    if kind not in BUILT_IN:
        raise ValueError(f"no built-in adapter type {kind}; built-in types are {', '.join(sorted(BUILT_IN))}")
    return BUILT_IN[kind]
