"""The `[github]` config table."""

import re
from pathlib import Path

import pytest

from starpulse.github.model.github_config import GitHub, GitHubConfigError, parse_github
from starpulse.runtime.config import ConfigError, load


def test_no_table_is_none() -> None:
    assert parse_github(None) is None


def test_a_table_takes_defaults_for_what_it_omits() -> None:
    table = parse_github({"secret_env": "HOOK", "organisation": "acme"})
    assert table == GitHub(secret_env="HOOK", organisation="acme")
    assert (table.host, table.max_body_bytes, table.database_url) == ("127.0.0.1", 5 * 1024 * 1024, None)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("x", "github must be a [github] table"),
        ({"organisation": "acme"}, "secret_env"),
        ({"secret_env": "HOOK"}, "organisation or repositories"),
        ({"secret_env": "HOOK", "organisation": "acme", "color": 1}, "unknown key(s) color"),
        ({"secret_env": "HOOK", "repositories": ["acme"]}, "owner/name"),
        ({"secret_env": "HOOK", "organisation": "acme", "max_body_bytes": 0}, "max_body_bytes"),
        ({"secret_env": "HOOK", "organisation": "acme", "port": 70000}, "port"),
        ({"secret_env": "HOOK", "organisation": "acme", "reconcile_interval_s": 0}, "reconcile_interval_s"),
        ({"secret_env": "HOOK", "organisation": "acme", "reconcile_token_env": ""}, "reconcile_token_env"),
    ],
)
def test_a_table_the_listener_cannot_run_names_the_key_to_fix(raw: object, message: str) -> None:
    with pytest.raises(GitHubConfigError, match=re.escape(message)):
        parse_github(raw)


def test_a_repository_or_an_organisation_member_is_accepted() -> None:
    table = parse_github({"secret_env": "HOOK", "organisation": "acme", "repositories": ["solo/tool"]})
    assert table is not None
    assert [table.accepts(name) for name in ("acme/a", "solo/tool", "solo/other", "acmeco/a")] == [True, True, False, False]


def test_the_config_loads_the_table_and_refuses_a_bad_one_as_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "starpulse.toml"
    assert load(None).github is None

    path.write_text('[github]\nsecret_env = "HOOK"\norganisation = "acme"\nmax_body_bytes = 1024\n')
    assert load(path).github == GitHub(secret_env="HOOK", organisation="acme", max_body_bytes=1024)

    path.write_text('[github]\nsecret_env = "HOOK"\n')
    with pytest.raises(ConfigError, match="organisation or repositories"):
        load(path)


def test_the_reconcile_keys_default_to_off_and_ten_minutes_and_are_read_when_given() -> None:
    off = parse_github({"secret_env": "HOOK", "organisation": "acme"})
    on = parse_github(
        {"secret_env": "HOOK", "organisation": "acme", "reconcile_token_env": "GH_APP", "reconcile_interval_s": 60}
    )

    assert (off.reconcile_token_env, off.reconcile_interval_s) == (None, 600)
    assert (on.reconcile_token_env, on.reconcile_interval_s) == ("GH_APP", 60)
