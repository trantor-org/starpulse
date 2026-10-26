"""The memory a worker is judged on is its proportional set size where the kernel reports one."""

import io
import os

import pytest

import starpulse.runtime.memory as memory_module

ROLLUP = "Rss:             900000 kB\nPss:              12345 kB\nShared_Clean:     800000 kB\n"


def _reading(files: dict[str, str]):
    def fake_open(path: str):
        if path not in files:
            raise FileNotFoundError(path)
        return io.StringIO(files[path])

    return fake_open


def test_the_proportional_size_is_the_pss_line_of_the_rollup_in_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_module, "open", _reading({"/proc/7/smaps_rollup": ROLLUP}), raising=False)

    assert memory_module._pss_proc(7) == 12345 * 1024


def test_a_kernel_without_the_rollup_gets_the_resident_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_module, "open", _reading({"/proc/7/statm": "100 50 10 0 0 0 0\n"}), raising=False)

    assert memory_module._pss_proc(7) == 50 * os.sysconf("SC_PAGE_SIZE")
