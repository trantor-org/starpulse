"""Re-exports the history from its adapter path for Trantor's direct import; T10 deletes this module."""

from starpulse.flow_metrics.adapters.outbound.history import *  # noqa: F403
from starpulse.flow_metrics.adapters.outbound.history import __all__  # noqa: F401
