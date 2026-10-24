"""The canary smoke's migrate step, the config it serves with, and its exit when the migrate step fails."""

from __future__ import annotations

import time
from pathlib import Path

import canary_smoke
import pytest
from canary_smoke import anchor_paths, render_config, step_migrate
from sqlalchemy import create_engine, text
from starpulse.event_log.migrate import migrate
from starpulse.event_log.tables import VERSION_TABLE


def history(path: Path) -> Path:
    """A store at the wheel's head, as `serve` leaves one."""
    migrate(create_engine(f"sqlite:///{path}"))
    return path


def test_render_config_points_database_url_at_the_copy(tmp_path: Path) -> None:
    config = 'mode = "ic"\ndatabase_url = "sqlite:////live/starpulse-history.sqlite"\n'

    rendered = render_config(config, tmp_path / "copy.sqlite")

    assert f'database_url = "sqlite:///{tmp_path / "copy.sqlite"}"' in rendered
    assert "/live/" not in rendered
    assert 'mode = "ic"' in rendered


def test_render_config_adds_database_url_when_absent(tmp_path: Path) -> None:
    rendered = render_config('mode = "ic"\n', tmp_path / "copy.sqlite")

    assert f'database_url = "sqlite:///{tmp_path / "copy.sqlite"}"' in rendered


def test_anchor_paths_reads_live_and_writes_scratch(tmp_path: Path) -> None:
    config = (
        'harnesses_file = "agent-harnesses.toml"\n'
        'event_log_archive_dir = "starpulse-state/starpulse-archive"\n'
        "\n[board]\n"
        'path = "../../.starpulse/board"\n'
        'task_file_name = "slug"\n'
        "\n[scheduler]\n"
        'state_dir = "starpulse-state"\n'
    )
    live, scratch = tmp_path / "infra" / "ai-vm-1", tmp_path / "scratch"

    anchored = anchor_paths(config, live, scratch)

    assert f'harnesses_file = "{live / "agent-harnesses.toml"}"' in anchored
    assert f'path = "{tmp_path / ".starpulse" / "board"}"' in anchored
    assert f'event_log_archive_dir = "{scratch / "starpulse-state" / "starpulse-archive"}"' in anchored
    assert f'state_dir = "{scratch / "starpulse-state"}"' in anchored
    assert 'task_file_name = "slug"' in anchored


def test_anchor_paths_reads_board_machine_and_drops_board_commands(tmp_path: Path) -> None:
    config = (
        "\n[board]\n"
        'machine = "../../.starpulse/machines/board.yaml"\n'
        'criteria = "../../.venv/bin/backlog-task criteria {id} --json"\n'
        'holds = "../../.venv/bin/backlog-task holds {id} --json --record-evidence"\n'
        'type = "native"\n'
    )
    live = tmp_path / "infra" / "ai-vm-1"

    anchored = anchor_paths(config, live, tmp_path / "scratch")

    assert f'machine = "{tmp_path / ".starpulse" / "machines" / "board.yaml"}"' in anchored
    assert "criteria" not in anchored
    assert "holds" not in anchored
    assert 'type = "native"' in anchored


def test_migrate_at_head_passes(tmp_path: Path) -> None:
    assert step_migrate(history(tmp_path / "head.sqlite")) is None


def test_migrate_past_head_fails_naming_migrate(tmp_path: Path) -> None:
    db = history(tmp_path / "ahead.sqlite")
    with create_engine(f"sqlite:///{db}").begin() as conn:
        conn.execute(text(f"UPDATE {VERSION_TABLE} SET version_num = '9999_from_a_newer_wheel'"))

    problem = step_migrate(db)

    assert problem is not None
    assert problem.startswith("migrate:")


def test_main_exits_nonzero_naming_migrate_before_serve(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = history(tmp_path / "ahead.sqlite")
    with create_engine(f"sqlite:///{db}").begin() as conn:
        conn.execute(text(f"UPDATE {VERSION_TABLE} SET version_num = '9999_from_a_newer_wheel'"))
    config = tmp_path / "starpulse.toml"
    config.write_text('mode = "ic"\n')
    machines = tmp_path / "machines"
    machines.mkdir()

    code = canary_smoke.main(
        ["--url", "http://127.0.0.1:1", "--config", str(config), "--machines", str(machines), "--db", str(db)]
    )

    assert code != 0
    assert "migrate:" in capsys.readouterr().out


def test_env_passes_pythonpath_and_no_other_host_variable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/live/lib")
    monkeypatch.setenv("SECRET_TOKEN", "do-not-pass")

    environ = canary_smoke.env(tmp_path, 'token_env = "STARPULSE_X"\n')

    assert environ["PYTHONPATH"] == "/live/lib"
    assert "SECRET_TOKEN" not in environ
    assert environ["STARPULSE_X"].startswith("canary-placeholder-")


class Serve:
    """A `serve` process that stays up: `hold` reads only its pid and poll."""

    pid = 1
    returncode = None

    def poll(self) -> int | None:
        return None


def test_hold_runs_the_board_check_inside_its_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(canary_smoke, "HOLD", 0.2)
    monkeypatch.setattr(canary_smoke, "SAMPLE", 0.05)
    monkeypatch.setattr(canary_smoke, "live_children", lambda parent, log: {"web": 10})
    monkeypatch.setattr(canary_smoke, "check", lambda port, parent, expected, log: None)
    start = time.monotonic()
    ran: list[float] = []

    problem = canary_smoke.hold(Serve(), 1, {"web"}, tmp_path / "log", during=lambda: ran.append(time.monotonic()))

    assert problem is None
    assert ran and ran[0] - start < 0.1
    assert time.monotonic() - start < 0.4


def test_hold_reports_a_restart_after_the_board_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    children = iter([{"web": 10}, {"web": 10}, {"web": 11}])
    monkeypatch.setattr(canary_smoke, "HOLD", 0.3)
    monkeypatch.setattr(canary_smoke, "SAMPLE", 0.05)
    monkeypatch.setattr(canary_smoke, "live_children", lambda parent, log: next(children, {"web": 11}))
    monkeypatch.setattr(canary_smoke, "check", lambda port, parent, expected, log: None)

    problem = canary_smoke.hold(Serve(), 1, {"web"}, tmp_path / "log", during=lambda: None)

    assert problem is not None and "restarted" in problem


def test_hold_returns_the_board_problem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(canary_smoke, "live_children", lambda parent, log: {"web": 10})

    problem = canary_smoke.hold(Serve(), 1, {"web"}, tmp_path / "log", during=lambda: "board: no card")

    assert problem == "board: no card"
