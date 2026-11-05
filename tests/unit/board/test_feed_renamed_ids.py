"""A task renamed on disk (`TASK-10987` to `PROP-84`) while the read model still keys it by the old id answers to both."""

from pathlib import Path

import pytest
from starpulse.contracts.adapters import BoardTask

from tests.machine_feed import MachineFeed
from tests.machines import MACHINES, ROLES


@pytest.fixture
def rig(tmp_path: Path) -> MachineFeed:
    rig = MachineFeed(tmp_path / "log.db", MACHINES, roles=ROLES)
    rig.put_task("TASK-10987", {"title": "Renamed", "state": "ready"})
    rig.feed.put(BoardTask(id="PROP-84", team="demo", title="Renamed", lane="ready", aliases=("TASK-10987",)))
    return rig


@pytest.mark.parametrize("asked", ["PROP-84", "TASK-10987"])
def test_either_id_finds_the_open_task(rig: MachineFeed, asked: str) -> None:
    assert rig.feed.is_open(asked)
    assert rig.feed.task(asked) is not None


def test_an_unknown_id_is_still_missing(rig: MachineFeed) -> None:
    assert not rig.feed.is_open("PROP-999")
    assert rig.feed.task("PROP-999") is None
