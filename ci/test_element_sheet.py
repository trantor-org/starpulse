"""The element sheet names a role for every palette token, so a new token cannot ship without a line saying what it is for."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def declared_tokens() -> set[str]:
    """The names in style.css's palette block: the first `:root`, which the layout tokens' second one follows."""
    css = (ROOT / "starpulse/web/src/style.css").read_text()
    block = css[css.index(":root") : css.index("}", css.index(":root"))]
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.DOTALL)
    return set(re.findall(r"(--[\w-]+)\s*:", block))


def roles() -> set[str]:
    """The tokens `ROLES` in elements.js gives a role."""
    js = (ROOT / "design/elements/elements.js").read_text()
    table = js[js.index("const ROLES") : js.index("const tokens")]
    return set(re.findall(r'"(--[\w-]+)":', table))


def test_every_palette_token_has_a_role_and_every_role_names_a_token() -> None:
    declared = declared_tokens()
    assert len(declared) > 30  # the block was read, not an empty match
    assert roles() == declared
