"""The read timing and listen backlog the page and `serve` share. It imports no context, so `serve` reads it without a page module."""

#: The default of `slow_read_seconds`.
SLOW_READ_S = 1.0

#: Connections the kernel queues for the server to accept: a crowd of pages connecting at once fits in it, where the
#: stock 5 drops the rest's SYNs and each waits out a 1 s retransmit before its first byte.
BACKLOG = 128
