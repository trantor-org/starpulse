"""A machine file is parsed once per process until it changes, and a caller's edit to what it read stays its own."""

from pathlib import Path

import pytest
import yaml
from starpulse.machine_engine.adapters import machine_loader

MACHINE = """\
name: delivery
states:
  start: {initial: true}
  shipped: {final: true}
events:
  SHIPPED:
    - {from: start, to: shipped}
"""
EDITED = MACHINE.replace("  shipped: {final: true}", "  built: {}\n  shipped: {final: true}")


@pytest.fixture
def parses(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The YAML texts parsed while the test runs."""
    seen: list[str] = []
    parse = yaml.safe_load

    def counted(text: str) -> object:
        seen.append(text)
        return parse(text)

    monkeypatch.setattr(machine_loader.yaml, "safe_load", counted)
    return seen


def test_an_unchanged_machine_file_is_parsed_once(tmp_path: Path, parses: list[str]) -> None:
    path = tmp_path / "delivery.yaml"
    path.write_text(MACHINE)

    machine_loader.load_machine(path)
    machine_loader.load_machine(path)

    assert parses == [MACHINE]


def test_an_edited_machine_file_is_read_again(tmp_path: Path) -> None:
    path = tmp_path / "delivery.yaml"
    path.write_text(MACHINE)
    machine_loader.load_machine(path)

    path.write_text(EDITED)

    assert set(machine_loader._read(path)["states"]) == {"start", "built", "shipped"}


def test_a_callers_edit_to_a_read_document_does_not_reach_the_next_reader(tmp_path: Path) -> None:
    path = tmp_path / "delivery.yaml"
    path.write_text(MACHINE)

    machine_loader._read(path)["states"].clear()

    assert set(machine_loader._read(path)["states"]) == {"start", "shipped"}
