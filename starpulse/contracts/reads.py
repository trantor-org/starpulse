"""The listen backlog the page and `serve` share. It imports no context, so `serve` reads it without a page module."""

#: Connections the kernel queues for the server to accept: a crowd of pages connecting at once fits in it, where the
#: stock 5 drops the rest's SYNs and each waits out a 1 s retransmit before its first byte.
BACKLOG = 128
