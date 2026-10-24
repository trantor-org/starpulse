"""The poll interval a tail and its followers share; apart from the log so that importing it loads no database stack."""

#: How long an idle running tail waits before it polls anyway, in seconds. An append wakes it sooner; this bounds the
#: delivery latency of one that cannot, an append by another process.
DEFAULT_POLL_INTERVAL = 5.0
