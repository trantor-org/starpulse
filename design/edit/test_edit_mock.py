"""The edit mockup reads no resolution label: no name it does not define, and no label the page stopped reading."""

import re
from pathlib import Path

EDIT = Path(__file__).with_name("edit.js")


def test_edit_mock_uses_no_undefined_resolution_names() -> None:
    source = EDIT.read_text()

    assert not re.search(r"\bRESOLUTION\b", source)
    assert not re.search(r"\bnh\b", source)


def test_edit_mock_names_no_resolution_label() -> None:
    source = EDIT.read_text()

    assert "agent-resolvable" not in source
    assert "needs-human" not in source
