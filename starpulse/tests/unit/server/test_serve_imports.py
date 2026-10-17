"""Importing the HTTP server module leaves the database stack for the first store that opens."""

from __future__ import annotations

import subprocess
import sys

import pytest

# `python -X importtime` on SERVER (ai-vm-1, 2026-10-17): ~2.03 s before the defer, ~0.5-0.6 s after (gate: under 1.2 s).
SERVER = "starpulse._internal.server.server"


@pytest.mark.parametrize("heavy", ["sqlalchemy", "alembic"])
def test_server_import_does_not_load_the_database_stack(heavy: str) -> None:
    probe = f"import sys, importlib; importlib.import_module('{SERVER}'); print('{heavy}' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "False"
