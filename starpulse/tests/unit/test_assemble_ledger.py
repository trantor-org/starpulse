"""The server hands the feed each runs instance's `[runs.commit]`, so a task's run pairs with it by the parameter that names it."""

import time
from pathlib import Path

import pytest

from starpulse.config import load
from starpulse.server import assemble
from starpulse.tests import fake_board

CONFIG = """
[board]
type = "starpulse.tests.fake_board"
lanes = ["open", "shut"]

[[runs]]
name = "q"
type = "dagu"
url = "http://q.test"
"""


def _feed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, commit: str):
    monkeypatch.setattr(fake_board, "BUILT", [])
    path = tmp_path / "starpulse.toml"
    path.write_text(CONFIG + commit)
    _, feed = assemble(load(path), tmp_path, None, ())
    entered = time.time() - 60
    feed.size_suns(lambda: [("FAKE-1", entered, "open", "shut")])
    feed.set_dags(
        "q",
        [
            {
                "name": "nightly",
                "recent": [
                    {
                        "runId": "r1",
                        "status": "succeeded",
                        "startedAt": "2999-01-01T00:00:00Z",
                        "finishedAt": "2999-01-01T00:01:00Z",
                        "params": {"TICKET": "FAKE-1"},
                        "steps": {},
                    }
                ],
            }
        ],
        None,
    )
    return feed


def test_a_cued_workflow_of_an_instance_is_tied_so_its_recent_runs_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _feed(tmp_path, monkeypatch, "").tied("q") == {"nightly"}


def test_an_instances_task_key_pairs_a_run_with_the_task_that_entered_the_cued_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = _feed(tmp_path, monkeypatch, '[runs.commit]\ntask = "TICKET"\n')

    (row,) = feed.snapshot()["ledgers"]["SHUT"]
    assert (row["tasks"], row["runs"]["q/nightly"]["inferred"]) == (["FAKE-1"], False)


def test_an_instance_with_no_commit_keys_pairs_by_time_and_marks_it_inferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = _feed(tmp_path, monkeypatch, "")

    (row,) = feed.snapshot()["ledgers"]["SHUT"]
    assert row["runs"]["q/nightly"]["inferred"] is True
