"""Building the hub's gate from its config and environment: the secrets it needs, and the tokens that must differ."""

from __future__ import annotations

import pytest

pytest.importorskip("jwt", reason="the hub extras are not installed")

from starpulse.oidc import Gate, build
from starpulse.settings.config import OidcSettings

SETTINGS = OidcSettings(
    issuer="https://id.example.test/realm",
    client_id="starpulse-hub",
    client_secret_env="HUB_SECRET",
    redirect_uri="https://hub.example.test/auth/callback",
    allowed_groups=("ops",),
    engine_token_env="HUB_ENGINE",
)


def test_a_gate_is_built_from_the_variables_the_settings_name() -> None:
    assert isinstance(build(SETTINGS, {"HUB_SECRET": "s", "HUB_ENGINE": "e"}, {"cron": "c"}), Gate)


def test_a_missing_client_secret_is_refused_naming_its_variable() -> None:
    with pytest.raises(ValueError, match="HUB_SECRET is not set"):
        build(SETTINGS, {"HUB_ENGINE": "e"}, {})


def test_a_named_but_unset_engine_token_variable_is_refused() -> None:
    with pytest.raises(ValueError, match="HUB_ENGINE is not set"):
        build(SETTINGS, {"HUB_SECRET": "s"}, {})


def test_the_engine_token_may_not_equal_an_instances_token() -> None:
    with pytest.raises(ValueError, match="engine token and instance cron hold the same token"):
        build(SETTINGS, {"HUB_SECRET": "s", "HUB_ENGINE": "same"}, {"cron": "same"})


def test_a_hub_with_no_engine_token_variable_has_no_engine_access() -> None:
    plain = OidcSettings(**{**SETTINGS.__dict__, "engine_token_env": None})

    assert isinstance(build(plain, {"HUB_SECRET": "s"}, {}), Gate)
