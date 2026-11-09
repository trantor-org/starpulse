"""Shorten the serving process's scheduling slice.

The Page API's tail at host load 100+ is run-queue delay, not read cost: a request wakes its thread about four times
(accept, read, worker hop, write), and each wake waits out the slice of whatever agent CPU hog holds the core (2.8 ms
by default under EEVDF). A thread asking for a 100 us slice has the earlier virtual deadline, so a wake preempts the
hog. No unit directive sets it and `ExecStart` stays `serve --config`, so the process asks for itself, unprivileged:
`sched_setattr` keeps the policy and nice level and sets only `sched_runtime`. Threads started afterwards inherit it.
"""

from __future__ import annotations

import ctypes
import os
import platform

SERVE_SLICE_NS = 100_000  # the kernel's floor; a longer ask only lengthens the wait behind a hog
_SYS_SCHED_SETATTR = {"x86_64": 314, "aarch64": 274}


class _SchedAttr(ctypes.Structure):  # struct sched_attr, SCHED_ATTR_SIZE_VER0
    _fields_ = (
        ("size", ctypes.c_uint32),
        ("sched_policy", ctypes.c_uint32),
        ("sched_flags", ctypes.c_uint64),
        ("sched_nice", ctypes.c_int32),
        ("sched_priority", ctypes.c_uint32),
        ("sched_runtime", ctypes.c_uint64),
        ("sched_deadline", ctypes.c_uint64),
        ("sched_period", ctypes.c_uint64),
    )


def _syscall(attr: _SchedAttr) -> int:  # pragma: no mutate block — kernel boundary
    number = _SYS_SCHED_SETATTR.get(platform.machine())
    if number is None:
        return -1
    return int(ctypes.CDLL(None, use_errno=True).syscall(number, 0, ctypes.byref(attr), 0))


def shorten_slice(slice_ns: int = SERVE_SLICE_NS) -> bool:
    """Give the calling thread, and the threads it starts, a `slice_ns` slice; False when the kernel refuses."""
    if not hasattr(os, "sched_getscheduler"):  # absent on macOS: the policy reads as unavailable
        return False
    attr = _SchedAttr(
        size=ctypes.sizeof(_SchedAttr),
        sched_policy=os.sched_getscheduler(0),
        sched_nice=os.getpriority(os.PRIO_PROCESS, 0),
        sched_runtime=slice_ns,
    )
    return _syscall(attr) == 0
