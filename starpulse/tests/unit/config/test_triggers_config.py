"""The `[[triggers]]` tables: each declares the run a board event starts, and a table the view cannot run is refused."""

from pathlib import Path

import pytest

from starpulse._internal.config.config import ConfigError, load
from starpulse._internal.config.triggers import Trigger

_RUNS = """
[[runs]]
name = "dagu"
type = "dagu"
url = "http://dagu.invalid"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return path


def test_no_table_declares_no_trigger(tmp_path: Path) -> None:
    assert load(None).triggers == load(_write(tmp_path, _RUNS)).triggers == ()


def test_a_table_declares_the_event_the_run_and_the_filter(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _RUNS
        + """
[[triggers]]
on = "lane"
start = "dagu/reconcile"
when = { lane = { equals = "done" }, team = { in = ["core", "ops"] } }

[[triggers]]
on = "machine"
start = "dagu/start-criteria"
""",
    )

    assert load(path).triggers == (
        Trigger("lane", "dagu/reconcile", {"lane": {"equals": "done"}, "team": {"in": ["core", "ops"]}}),
        Trigger("machine", "dagu/start-criteria", {}),
    )


@pytest.mark.parametrize(
    ("table", "complaint"),
    [
        ('start = "dagu/reconcile"', "on"),
        ('on = "lane"', "start"),
        ('on = "queue"\nstart = "dagu/reconcile"', "on must be"),
        ('on = "lane"\nstart = "reconcile"', "<instance>/<workflow>"),
        ('on = "lane"\nstart = "ghost/reconcile"', "ghost"),
        ('on = "lane"\nstart = "dagu/reconcile"\nonce = true', "once"),
        ('on = "lane"\nstart = "dagu/reconcile"\nwhen = { lane = "done" }', "when"),
        ('on = "lane"\nstart = "dagu/reconcile"\nwhen = { lane = { equals = "done", exists = true } }', "when"),
        ('on = "lane"\nstart = "dagu/reconcile"\nwhen = {}', "when"),
    ],
)
def test_a_table_the_view_cannot_run_is_refused_naming_the_key(tmp_path: Path, table: str, complaint: str) -> None:
    path = _write(tmp_path, _RUNS + f"\n[[triggers]]\n{table}\n")

    with pytest.raises(ConfigError, match=complaint):
        load(path)


def test_a_push_only_instance_cannot_be_started(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[[runs]]\nname = "ci"\ntoken_env = "CI_TOKEN"\n\n[[triggers]]\non = "lane"\nstart = "ci/reconcile"\n',
    )

    with pytest.raises(ConfigError, match="ci"):
        load(path)
