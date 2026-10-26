"""A child told to report readiness writes one byte to the descriptor its environment names."""

import os

from starpulse._internal.server.hold import READY_FD_ENV, announce_ready


def test_announce_ready_writes_a_byte_to_the_named_descriptor_and_forgets_it() -> None:
    read_end, write_end = os.pipe()
    environ = {READY_FD_ENV: str(write_end)}
    announce_ready(environ)

    assert os.read(read_end, 1) == b"1"
    assert environ == {}
    os.close(read_end)


def test_announce_ready_without_a_descriptor_or_with_a_closed_one_does_nothing() -> None:
    announce_ready({})
    read_end, write_end = os.pipe()
    os.close(read_end)
    os.close(write_end)
    announce_ready({READY_FD_ENV: str(write_end)})
