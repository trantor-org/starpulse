"""The memory a worker is judged on is its proportional set size, so pages it shares with a sibling count once between them."""

import os
import subprocess
import sys

import pytest
import starpulse.runtime.memory as memory_module

MB = 1024 * 1024

#: Touches 64 MB, forks, and prints the child's pid: the child shares every page with its parent until it writes one.
SHARER = """
import os, time
block = bytearray(b"x" * (64 * 1024 * 1024))
pid = os.fork()
if pid == 0:
    time.sleep(60)
else:
    print(pid, flush=True)
    time.sleep(60)
"""


def _resident(pid: int) -> int:
    with open(f"/proc/{pid}/statm") as statm:
        return int(statm.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads Linux /proc")
def test_pages_a_forked_child_shares_with_its_parent_count_half_to_each() -> None:
    parent = subprocess.Popen([sys.executable, "-c", SHARER], stdout=subprocess.PIPE, text=True)
    try:
        child = int(parent.stdout.readline())

        used = memory_module.memory_reader()(child)

        assert used > 32 * MB  # its half of the block is still its own
        assert used < _resident(child) * 0.75  # the resident size would count the whole block
    finally:
        parent.kill()
        parent.wait()
        subprocess.run(["kill", "-9", str(child)], capture_output=True)
