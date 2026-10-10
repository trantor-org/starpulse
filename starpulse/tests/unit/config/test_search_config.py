"""The `[search]` table: search is lexical with none, and a table it cannot read is refused naming the key."""

import re
from pathlib import Path

import pytest

from starpulse._internal.config.config import ConfigError, load
from starpulse._internal.config.search import Search


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return path


def test_no_table_keeps_search_lexical(tmp_path: Path) -> None:
    assert load(None).search == load(_write(tmp_path, "")).search == Search()
    assert Search().embeddings_url is None


def test_a_table_names_the_embeddings_endpoint_its_model_and_the_variable_holding_its_token(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[search]
embeddings_url = "http://localhost:8080/v1/embeddings"
model = "nomic-embed-text"
token_env = "EMBEDDINGS_TOKEN"
""",
    )

    assert load(path).search == Search("http://localhost:8080/v1/embeddings", "nomic-embed-text", "EMBEDDINGS_TOKEN")


def test_an_empty_table_is_lexical(tmp_path: Path) -> None:
    assert load(_write(tmp_path, "[search]\n")).search == Search()


@pytest.mark.parametrize(
    ("table", "refusal"),
    [
        ('search = "x"', "search must be a [search] table"),
        ("[search]\nurl = 'x'", "search: unknown key(s) url"),
        ("[search]\nembeddings_url = 1", "search: embeddings_url must be an http:// or https:// address"),
        ("[search]\nembeddings_url = 'ftp://h/e'\nmodel = 'm'", "search: embeddings_url must be an http:// or https://"),
        ("[search]\nembeddings_url = 'http://h/e'", "search: model is required with embeddings_url"),
        ("[search]\nmodel = 'm'", "search: model needs embeddings_url"),
        (
            "[search]\nembeddings_url = 'http://h/e'\nmodel = 'm'\ntoken_env = 'not a name'",
            "search: token_env must be the name of an environment variable",
        ),
    ],
)
def test_a_table_the_view_cannot_read_is_refused_naming_the_key(tmp_path: Path, table: str, refusal: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(refusal)):
        load(_write(tmp_path, table))
