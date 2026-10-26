"""`GET /metrics` names the page build the `build` event names, so a rebuild is observable from Prometheus."""

import json
import re
import urllib.request
from pathlib import Path

from starpulse.board.board_feed import BoardFeed
from starpulse.runtime.adapter_kit import serve, url
from starpulse.views.page_server import PageServer

from tests.machines import MACHINES, ROLES


def _metrics(server: PageServer) -> list[str]:
    with urllib.request.urlopen(url(server, "/metrics"), timeout=5) as resp:
        return resp.read().decode().splitlines()


def _build_event_id(server: PageServer) -> str:
    with urllib.request.urlopen(url(server, "/api/events"), timeout=5) as resp:
        frames = ""
        while "event: build" not in frames or frames.count("\n\n") < 2:
            frames += resp.read1(65536).decode()
    data = frames.split("event: build\ndata: ", 1)[1].split("\n", 1)[0]
    return json.loads(data)["id"]


def test_metrics_lists_the_build_id_the_build_event_names(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES)) as server:
        build = _build_event_id(server)
        lines = _metrics(server)

    assert re.fullmatch(r"[0-9a-f]{12}", build)
    assert f'starpulse_page_build_info{{build="{build}"}} 1' in lines


def test_metrics_has_no_build_series_while_static_holds_no_build(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES)) as server:
        (tmp_path / "static" / "index.html").unlink()
        lines = _metrics(server)

    assert not [line for line in lines if "starpulse_page_build_info" in line]


def test_metrics_times_the_snapshot_builds(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES)) as server:
        _build_event_id(server)  # a connect makes the cache build its first snapshot
        lines = _metrics(server)

    assert "# TYPE starpulse_snapshot_build_seconds summary" in lines
    count = next(line for line in lines if line.startswith("starpulse_snapshot_build_seconds_count "))
    total = next(line for line in lines if line.startswith("starpulse_snapshot_build_seconds_sum "))
    assert int(count.split()[1]) >= 1
    assert float(total.split()[1]) > 0
