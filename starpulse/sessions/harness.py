"""The harness adapter `[harness]` names: StarPulse reaches a session's harness only through it."""

from collections.abc import Mapping
from importlib import import_module

from starpulse.sessions.ports.harness import SessionHarness

#: The adapters that ship, each a `module:class` taking the environment and the transcripts directory.
ADAPTERS = {"claude": "starpulse.sessions.adapters.outbound.claude_code:ClaudeCodeSessions"}


ADAPTER_MODULES = tuple(target.partition(":")[0] for target in ADAPTERS.values())


def configured(name: str, environ: Mapping[str, str], transcripts: str | None = None) -> SessionHarness:
    """The adapter `name` names, built over `environ`; a `KeyError` when no adapter has that name."""
    module, _, cls = ADAPTERS[name].partition(":")
    return getattr(import_module(module), cls)(environ, transcripts)
