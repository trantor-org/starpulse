"""The adapters StarPulse ships, and the names a bare `[board]` or `[[runs]]` `type` resolves to.

This module imports nothing, so the config can read the table without importing an adapter.
"""

#: Built-in type -> module. A dotted type is a module path an installed package provides and is not listed.
BUILT_IN = {
    "native": "starpulse.adapters.boards.native",
    "upstream_backlog": "starpulse.adapters.boards.upstream_backlog",
    "jira": "starpulse.adapters.boards.jira",
    "dagu": "starpulse.adapters.runs.dagu",
    "github_actions": "starpulse.adapters.runs.github_actions",
    "systemd": "starpulse.adapters.runs.systemd",
}


def module_name(kind: str) -> str:
    """The module a `[board]` or `[[runs]]` type names: a dotted path as it is, a bare name through `BUILT_IN`."""
    if "." in kind:
        return kind
    if kind not in BUILT_IN:
        raise ValueError(f"no built-in adapter type {kind}; built-in types are {', '.join(sorted(BUILT_IN))}")
    return BUILT_IN[kind]
