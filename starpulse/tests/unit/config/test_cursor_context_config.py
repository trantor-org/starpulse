"""The `[cursor_context]` table: where a Cursor session is held to a token limit, and what it refuses."""

import re
from pathlib import Path

import pytest

from starpulse._internal.config.config import ConfigError, load
from starpulse._internal.config.cursor_context import CursorContext


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return path


def test_no_table_holds_a_session_to_150k_tokens_of_a_200k_window(tmp_path: Path) -> None:
    expected = CursorContext(limit_tokens=150_000, window_tokens=200_000, wrapup_s=600.0)

    assert load(None).cursor_context == load(_write(tmp_path, "")).cursor_context == expected


def test_a_table_sets_the_limit_the_window_and_the_wrap_up_deadline(tmp_path: Path) -> None:
    path = _write(tmp_path, "[cursor_context]\nlimit_tokens = 120000\nwindow_tokens = 256000\nwrapup_s = 300\n")

    assert load(path).cursor_context == CursorContext(120_000, 256_000, 300.0)


@pytest.mark.parametrize(
    ("table", "refusal"),
    [
        ("limit_tokens = 0", "cursor_context: limit_tokens must be a positive whole number"),
        ("limit_tokens = 'x'", "cursor_context: limit_tokens must be a positive whole number"),
        ("window_tokens = -1", "cursor_context: window_tokens must be a positive whole number"),
        ("limit_tokens = 300000", "cursor_context: limit_tokens must not exceed window_tokens"),
        ("wrapup_s = 0", "cursor_context: wrapup_s must be a positive number of seconds"),
        ("limit = 1", "cursor_context: unknown key(s) limit"),
    ],
)
def test_a_table_it_cannot_read_is_refused_naming_the_key(tmp_path: Path, table: str, refusal: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(refusal)):
        load(_write(tmp_path, f"[cursor_context]\n{table}\n"))
