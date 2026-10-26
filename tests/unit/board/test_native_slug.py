"""The native board's slug: a lowercase, hyphen-only name of at most `_SLUG_MAX` characters that never ends mid-word."""

import re

import pytest
from starpulse.board.adapters.native import _SLUG_MAX, _slug

_VALID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("Migrate the workers to the new queue", "migrate-the-workers"),
        ("Migrate the workers to the new queue of the day", "migrate-the-workers"),
        ("ab-cdefghijklmnopqr-xyz", "ab-cdefghijklmnopqr"),
        ("Let a native StarPulse board name task files", "let-a-native"),
        ("Check the nightly sweep 2026-10-09", "check-the-nightly-2026-10-09"),
        ("Supercalifragilisticexpialidocious", "supercalifragilisti"),
        ("What's new: Ünïcode & symbols", "what-s-new-n-code"),
        ("!!!", "untitled"),
    ],
)
def test_native_slug_caps_at_a_word_and_keeps_a_trailing_date(title: str, slug: str) -> None:
    assert _slug(title) == slug


@pytest.mark.parametrize(
    "title",
    [
        "Migrate the workers to the new queue of the day",
        "Fix the parser and the lexer and the tokens",
        "Re-fit the model for the north star scale",
        "  --  Leading and trailing punctuation!!  --  ",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ],
)
def test_native_slug_is_a_valid_slug_of_at_most_the_cap(title: str) -> None:
    slug = _slug(title)

    assert _VALID.fullmatch(slug), slug
    assert len(slug) <= _SLUG_MAX
