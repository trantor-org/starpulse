"""A bare `[board]` or `[[runs]]` type resolves through the built-in table, and each documented one loads."""

import importlib
import re
from pathlib import Path

import pytest

from starpulse._internal.config.adapter_types import BUILT_IN, module_name

DOCS = next(root for root in Path(__file__).resolve().parents if (root / "README.md").is_file()) / "docs"
#: The docs that show a `[board]` or `[[runs]]` table: the config file, and the sources a runs adapter reads.
CONFIG_DOCS = (DOCS / "serving.md", DOCS / "sources.md")


def _documented_bare_types() -> set[str]:
    """Every `type = "name"` the config docs show, commented or not, that names no dotted module."""
    text = "\n".join(doc.read_text() for doc in CONFIG_DOCS)
    return {name for name in re.findall(r'^#?\s*type = "([^"]+)"', text, re.MULTILINE) if "." not in name}


def _offers_an_adapter(module) -> bool:
    return callable(getattr(module, "board", None)) or (
        callable(getattr(module, "start", None)) and callable(getattr(module, "follow", None))
    )


def test_the_config_docs_document_bare_types() -> None:
    assert {"native", "upstream_backlog", "jira", "dagu", "github_actions", "systemd"} <= _documented_bare_types()


@pytest.mark.parametrize("kind", sorted(_documented_bare_types()))
def test_builtin_types_every_documented_bare_type_loads(kind: str) -> None:
    assert kind in BUILT_IN, f"{kind} is documented but missing from the built-in table"
    assert _offers_an_adapter(importlib.import_module(module_name(kind)))


@pytest.mark.parametrize("kind", sorted(BUILT_IN))
def test_builtin_types_every_table_entry_names_an_importable_adapter(kind: str) -> None:
    module = importlib.import_module(module_name(kind))

    assert module.__name__.startswith(("starpulse._internal.board.", "starpulse._internal.runs.")), "a built-in adapter lives in its feature package"
    assert _offers_an_adapter(module)


def test_builtin_types_a_dotted_type_is_a_module_path_as_it_is() -> None:
    assert module_name("starpulse.tests.fake_board") == "starpulse.tests.fake_board"


def test_builtin_types_an_unknown_bare_type_is_refused() -> None:
    with pytest.raises(ValueError, match="nowhere"):
        module_name("nowhere")
