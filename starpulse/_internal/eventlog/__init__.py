"""The event log: the tables, the log and the history kept in them, the level's flow numbers and the migrations that version the schema."""

#: How long an idle running tail waits before it polls anyway, in seconds. An append wakes it sooner; this bounds the
#: delivery latency of one that cannot, an append by another process.
DEFAULT_POLL_INTERVAL = 5.0
