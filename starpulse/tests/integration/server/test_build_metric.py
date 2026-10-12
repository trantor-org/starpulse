"""`GET /metrics` names the page build the `build` event names, so a rebuild is observable from Prometheus."""

import json
import re
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse.tests.machines import MACHINES


def _metrics(server: ThreadingHTTPServer) -> list[str]:
    with urllib.request.urlopen(url(server, "/metrics"), timeout=5) as resp:
        return resp.read().decode().splitlines()


def _build_event_id(server: ThreadingHTTPServer) -> str:
    with urllib.request.urlopen(url(server, "/api/events"), timeout=5) as resp:
        frames = ""
        while "event: build" not in frames or frames.count("\n\n") < 2:
            frames += resp.read1(65536).decode()
    data = frames.split("event: build\ndata: ", 1)[1].split("\n", 1)[0]
    return json.loads(data)["id"]


def test_metrics_lists_the_build_id_the_build_event_names(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed(machines=MACHINES)) as server:
        build = _build_event_id(server)
        lines = _metrics(server)

    assert re.fullmatch(r"[0-9a-f]{12}", build)
    assert f'starpulse_page_build_info{{build="{build}"}} 1' in lines


def test_metrics_has_no_build_series_while_static_holds_no_build(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed(machines=MACHINES)) as server:
        (tmp_path / "static" / "index.html").unlink()
        lines = _metrics(server)

    assert not [line for line in lines if "starpulse_page_build_info" in line]
