"""The `[search]` config table: the optional embeddings service that ranks board search by meaning.

Search is lexical (SQLite FTS5) with no table. `embeddings_url` names an OpenAI-compatible embeddings endpoint, local or
cloud, and with it set the instance embeds each task's text and blends the vector's similarity into the lexical ranking.
`model` is the model name the endpoint is asked for, and `token_env` the environment variable holding its bearer token
(the token itself is never in this file). With no `embeddings_url` nothing calls out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

__all__ = ["Search", "SearchError", "parse_search"]

_KEYS = {"embeddings_url", "model", "token_env"}
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class SearchError(ValueError):
    """The table cannot be read; the message names the key to fix."""


@dataclass(frozen=True)
class Search:
    embeddings_url: str | None = None
    """The embeddings endpoint (`POST` of `{model, input}`); none: search is lexical and nothing calls out."""
    model: str | None = None
    """The model the endpoint is asked for; required with `embeddings_url`."""
    token_env: str | None = None
    """The environment variable holding the endpoint's bearer token; none: requests carry no credentials."""


def parse_search(raw: object) -> Search:
    """The `[search]` table, or the lexical-only one for `None`; each refusal names the key to fix."""
    if raw is None:
        return Search()
    if not isinstance(raw, dict):
        raise SearchError("search must be a [search] table")
    if unknown := sorted(raw.keys() - _KEYS):
        raise SearchError(f"search: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_KEYS))}")
    url, model, token_env = raw.get("embeddings_url"), raw.get("model"), raw.get("token_env")
    address = urlsplit(url) if isinstance(url, str) else None
    if url is not None and not (address and address.scheme in {"http", "https"} and address.netloc):
        raise SearchError("search: embeddings_url must be an http:// or https:// address")
    if model is not None and not (isinstance(model, str) and model):
        raise SearchError("search: model must be text")
    if url is not None and model is None:
        raise SearchError("search: model is required with embeddings_url")
    if url is None and (model is not None or token_env is not None):
        raise SearchError(f"search: {'model' if model is not None else 'token_env'} needs embeddings_url")
    if token_env is not None and not (isinstance(token_env, str) and _ENV_NAME.fullmatch(token_env)):
        raise SearchError("search: token_env must be the name of an environment variable")
    return Search(url, model, token_env)
