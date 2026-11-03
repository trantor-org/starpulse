"""The memory a worker is judged on is its proportional set size where the kernel reports one."""

import os
import sys

import pytest
import starpulse.runtime.memory as memory_module


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="proportional size is Linux's")
def test_the_proportional_size_of_a_live_process_is_at_most_its_resident_size() -> None:
    pss = memory_module._pss(os.getpid())

    assert 0 < pss <= memory_module._rss(os.getpid())
