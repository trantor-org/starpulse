"""The GitHub App JWT that the `/app/...` endpoints require: GitHub rejects an installation token or a personal one there."""

import os
import time
from collections.abc import Callable
from pathlib import Path

import jwt

__all__ = ["app_jwt"]

#: GitHub refuses a JWT that lives over ten minutes, and `iat` is set back a minute for clock drift.
_LIFETIME_S = 540
_DRIFT_S = 60


def _setting(name: str) -> str:
    if not (value := os.environ.get(name, "").strip()):
        raise RuntimeError(f"{name} is unset: the App's {'id' if name == 'GH_APP_ID' else 'key path'} signs `/app/...` reads")
    return value


def app_jwt(clock: Callable[[], float] = time.time) -> str:
    """A JWT for the App `GH_APP_ID`, signed RS256 with the key at `GH_APP_PRIVATE_KEY_PATH`, valid for nine minutes."""
    issued = int(clock())
    claims = {"iss": _setting("GH_APP_ID"), "iat": issued - _DRIFT_S, "exp": issued + _LIFETIME_S}
    return jwt.encode(claims, Path(_setting("GH_APP_PRIVATE_KEY_PATH")).read_text(), algorithm="RS256")
