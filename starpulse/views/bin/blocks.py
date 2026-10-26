"""The config blocks the views worker is built from or re-reads, in a leaf module so `runtime.closure` names them without
importing the worker."""

from starpulse._internal.config.config import Config


def api_built_blocks(config: Config) -> tuple:
    """What of `config` the page is built from at start; a change needs a new process."""
    return (config,)
