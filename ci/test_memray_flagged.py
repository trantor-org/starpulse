"""Rerunning flagged tests under memray: each reported test gets stats, and one that leaves none is reported, not dropped."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

CI = Path(__file__).resolve().parent


@pytest.mark.skipif(
    bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
    reason="memray reports no allocation for the test's 800 KB list on the free-threaded build, whatever the GIL state of this"
    " process: an extension that does not declare itself GIL-safe (grpc) re-enables it here, not in the rerun's fresh process",
)
def test_each_reported_test_gets_memray_stats_and_one_that_leaves_none_is_named_with_a_warning(tmp_path):
    (tmp_path / "test_x.py").write_text("def test_alloc():\n    assert len([0] * 100_000) == 100_000\n")
    report = tmp_path / "test-cost.json"
    rows = [
        {"nodeid": nodeid, "wall_s": 6.0, "cpu_s": 6.0, "peak_mb": 1.0}
        for nodeid in ("test_x.py::test_alloc", "test_x.py::test_gone")
    ]
    report.write_text(json.dumps({"tests": rows}))

    done = subprocess.run(
        [sys.executable, str(CI / "memray_flagged.py"), str(report), str(tmp_path / "memray")],
        cwd=tmp_path,
        env={**os.environ, "PYTEST_ADDOPTS": "-n 2", "TEST_COST_REPORT": "1"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    stats = {row["nodeid"]: row for row in json.loads((tmp_path / "memray" / "stats.json").read_text())["tests"]}
    assert set(stats) == {"test_x.py::test_alloc", "test_x.py::test_gone"}
    assert "Total memory allocated" in (tmp_path / "memray" / stats["test_x.py::test_alloc"]["stats"]).read_text()
    assert stats["test_x.py::test_gone"]["stats"] is None
    assert "::warning title=No memray stats::test_x.py::test_gone" in done.stdout
    assert "No memray stats::test_x.py::test_alloc" not in done.stdout
    assert json.loads(report.read_text()) == {"tests": rows}
