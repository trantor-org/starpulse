"""The stock server draws the harness machine a Claude Code session moves through, beside the Board."""

import json
import urllib.request
from pathlib import Path

from starpulse.api.adapter_kit import assembled, serve, url
from starpulse.settings.config import load
from starpulse.store.history import HistoryStore
from starpulse.tests.unit.test_claude_code import replay


def _get(server, path: str) -> dict:
    with urllib.request.urlopen(url(server, path), timeout=5) as resp:
        return json.loads(resp.read())


def test_the_native_board_draws_the_harness_machine_and_answers_its_history(tmp_path: Path) -> None:
    config = tmp_path / "starpulse.toml"
    config.write_text("")
    _, feed = assembled(load(config), tmp_path)
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", feed.machines)
    events = replay("feature/PROJ-1-add-x")
    for i, event in enumerate(events):
        store.record_machine(f"m{i}-0", {**event, "event_id": f"m{i}"})

    with serve(tmp_path, feed, history=store) as server:
        flows = [f["name"] for f in _get(server, "/api/snapshot")["flows"]]
        history = _get(server, "/api/history?task=PROJ-1&flow=harness")

    assert flows == ["board", "harness"]
    assert [step["event"] for step in history["path"]] == [e["event"] for e in events if e["task"] == "PROJ-1"]
