"""Gzip for what the server writes to a page that accepts it: a JSON body over `MIN_BYTES`, and every stream event."""

from __future__ import annotations

import gzip
import zlib
from collections.abc import Callable
from typing import BinaryIO, NamedTuple

#: A body this size or smaller is sent as it is: gzip's header and the page's decode cost more than it saves.
MIN_BYTES = 64 * 1024
#: 1.9 MB of snapshot JSON compresses in about 10 ms at level 6 and to the size level 9 gives, which takes up to twice as long.
LEVEL = 6


def accepts_gzip(accept_encoding: str | None) -> bool:
    """Whether an `Accept-Encoding` header lists `gzip` with a quality above zero."""
    for item in (accept_encoding or "").split(","):
        coding, _, params = item.partition(";")
        if coding.strip().lower() == "gzip":
            return params.replace(" ", "").lower() not in ("q=0", "q=0.0", "q=0.00", "q=0.000")
    return False


def compressed(body: bytes, accept_encoding: str | None) -> bytes | None:
    """`body` gzipped, or None when it is `MIN_BYTES` or smaller or the page does not accept gzip."""
    if len(body) <= MIN_BYTES or not accepts_gzip(accept_encoding):
        return None
    return gzip.compress(body, compresslevel=LEVEL, mtime=0)


class Encoded(NamedTuple):
    """A body and its gzip, made once for a body many pages read: gzip of a ~1 MB body takes tens of ms."""

    body: bytes
    #: None when the body is too small to be worth compressing.
    gzipped: bytes | None

    @classmethod
    def of(cls, body: bytes) -> Encoded:
        return cls(body, compressed(body, "gzip"))


def gzip_stream(out: BinaryIO) -> Callable[[bytes], None]:
    """A writer of `out` as one gzip stream that ends a deflate block after each write, so the page decodes
    every event or ping as it arrives rather than when the next fills the compressor's buffer."""
    deflater = zlib.compressobj(LEVEL, wbits=31)

    def write(data: bytes) -> None:
        out.write(deflater.compress(data) + deflater.flush(zlib.Z_SYNC_FLUSH))
        out.flush()

    return write
