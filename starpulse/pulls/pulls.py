"""Re-exports the pull store from its adapter path for Trantor's direct import; T10 deletes this module."""

from starpulse.pulls.adapters.outbound.pulls import *  # noqa: F403
from starpulse.pulls.adapters.outbound.pulls import __all__  # noqa: F401
