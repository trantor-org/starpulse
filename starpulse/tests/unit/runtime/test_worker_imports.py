"""A history or search worker imports its own context, not the whole HTTP server module."""

from __future__ import annotations

import subprocess
import sys

import pytest

SERVER = "starpulse.runtime.server"


@pytest.mark.parametrize(
    "worker", ["starpulse.flow_metrics.bin.flow_metrics_worker", "starpulse.board.bin.search_worker"]
)
def test_worker_entry_does_not_import_the_server(worker: str) -> None:
    probe = f"import sys, importlib; importlib.import_module('{worker}'); print('{SERVER}' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "False"
