"""A held task serves `interactive` false until its take-over is accepted, then true."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import next_event as _next_event
from starpulse._internal.kit.adapter_kit import serve as _serve
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.kit.adapter_kit import url as _url
from starpulse.tests.machines import MACHINES, ROLES


def _interactive(document: dict) -> dict[str, bool]:
    return {t["id"]: t["interactive"] for c in document["columns"] for t in c["tasks"]}


def test_a_held_task_is_interactive_only_after_its_take_over_is_accepted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("starpulse._internal.server.server._HELD_SETTLE_S", 0)
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "In Progress", assignee="session-1"))
    taken: list[str] = []

    def take_over(name: str) -> bool:
        taken.append(name)
        return True

    with _serve(tmp_path, feed, take_over=take_over) as server:
        with urllib.request.urlopen(_url(server, "/api/held?assignee=session-1"), timeout=5) as resp:
            _, before = _next_event(resp)
            request = urllib.request.Request(
                _url(server, "/api/take-over"),
                data=json.dumps({"task": "PROJ-1"}).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as posted:
                status = posted.status
            _, after = _next_event(resp)

    assert (status, taken) == (200, ["PROJ-1"])
    assert (_interactive(before), _interactive(after)) == ({"PROJ-1": False}, {"PROJ-1": True})
