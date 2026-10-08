"""StarPulse's one config file: where its tracker and orchestrator are and which adapters run."""

import sys
from pathlib import Path

import pytest

from starpulse.settings.config import (
    CommitKeys,
    Config,
    ConfigError,
    Forward,
    OidcSettings,
    Repo,
    Source,
    load,
    runs_adapter,
)
from starpulse.settings.harnesses import HarnessError


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "flow-view.toml"
    path.write_text(text)
    return path


def _refusal(tmp_path: Path, text: str) -> str:
    with pytest.raises(ConfigError) as refused:
        load(_write(tmp_path, text))
    return str(refused.value)


def test_a_config_names_the_tracker_and_the_mode(tmp_path: Path) -> None:
    path = _write(tmp_path, 'tracker_url = "http://tracker.example.test:6421"\n')

    assert load(path) == Config(tracker_url="http://tracker.example.test:6421", mode="ic", runs=())


def test_no_config_file_means_a_tracker_less_ic_view_without_runs() -> None:
    assert load(None) == Config(tracker_url=None, mode="ic", runs=())


def test_with_no_config_or_no_board_table_the_board_is_starpulses_own_native_board(tmp_path: Path) -> None:
    assert load(None).board_type == "native"
    assert load(_write(tmp_path, 'tracker_url = "http://tracker.example.test:6421"\n')).board_type == "native"


_TWO_INSTANCES = """
[[runs]]
name = "prod"
type = "dagu"
url = "http://prod.example.test:8085"
run_safe = ["nightly"]
[runs.domains]
Ops = ["nightly", "backup"]
Data = ["etl"]

[[runs]]
name = "staging"
type = "dagu"
url = "http://staging.example.test:8085"
run_safe = ["nightly", "etl"]
[runs.domains]
Ops = ["nightly"]
"""


def test_each_runs_instance_has_its_own_name_type_url_run_safe_and_domains(tmp_path: Path) -> None:
    prod, staging = load(_write(tmp_path, _TWO_INSTANCES)).runs

    assert (prod.name, prod.type, prod.url, prod.run_safe) == (
        "prod",
        "dagu",
        "http://prod.example.test:8085",
        ("nightly",),
    )
    assert prod.domains == {"Ops": ("nightly", "backup"), "Data": ("etl",)}
    assert (staging.name, staging.run_safe, staging.domains) == ("staging", ("nightly", "etl"), {"Ops": ("nightly",)})


def test_workflows_are_qualified_by_their_instance_and_a_shared_workflow_name_stays_two_workflows(
    tmp_path: Path,
) -> None:
    config = load(_write(tmp_path, _TWO_INSTANCES))

    assert config.qualified_domains() == {
        "Ops": ("prod/nightly", "prod/backup", "staging/nightly"),
        "Data": ("prod/etl",),
    }
    assert config.qualified_run_safe() == ("prod/nightly", "staging/nightly", "staging/etl")


def test_an_instance_without_run_safe_or_domains_declares_neither(tmp_path: Path) -> None:
    (only,) = load(_write(tmp_path, '[[runs]]\nname = "ci"\ntype = "dagu"\nurl = "http://ci.test"\n')).runs

    assert (only.run_safe, only.domains) == ((), {})


@pytest.mark.parametrize("value", ['"nightly"', "[1]", '["ok", 2]'])
def test_run_safe_must_be_a_list_of_workflow_names(tmp_path: Path, value: str) -> None:
    text = f'[[runs]]\nname = "ci"\ntype = "dagu"\nurl = "http://ci.test"\nrun_safe = {value}\n'

    assert _refusal(tmp_path, text) == "runs instance ci: run_safe must be a list of workflow names"


@pytest.mark.parametrize("value", ['"Ops"', '{ Ops = "nightly" }', "{ Ops = [1] }"])
def test_domains_must_map_a_domain_name_to_a_list_of_workflow_names(tmp_path: Path, value: str) -> None:
    text = f'[[runs]]\nname = "ci"\ntype = "dagu"\nurl = "http://ci.test"\ndomains = {value}\n'

    assert _refusal(tmp_path, text) == "runs instance ci: domains must map each domain name to a list of workflow names"


@pytest.mark.parametrize("name", ["", "a/b", 3])
def test_an_instance_name_is_a_non_empty_string_without_a_slash(tmp_path: Path, name: object) -> None:
    value = f'"{name}"' if isinstance(name, str) else name
    text = f'[[runs]]\nname = {value}\ntype = "dagu"\nurl = "http://ci.test"\n'

    assert _refusal(tmp_path, text) == "runs instance names must be non-empty text without a /"


def test_two_instances_cannot_share_a_name(tmp_path: Path) -> None:
    one = '[[runs]]\nname = "ci"\ntype = "dagu"\nurl = "http://ci.test"\n'

    assert _refusal(tmp_path, one + one) == "runs instance ci is configured twice"


@pytest.mark.parametrize("missing", ["name", "type", "url"])
def test_an_instance_needs_a_name_a_type_and_a_url(tmp_path: Path, missing: str) -> None:
    fields = {"name": '"ci"', "type": '"dagu"', "url": '"http://ci.test"'}
    text = "[[runs]]\n" + "".join(f"{k} = {v}\n" for k, v in fields.items() if k != missing)

    assert _refusal(tmp_path, text) == f"a runs instance needs {missing}"


def test_an_instance_with_a_token_and_no_type_or_url_is_push_only(tmp_path: Path) -> None:
    (only,) = load(_write(tmp_path, '[[runs]]\nname = "cron"\ntoken_env = "CRON_INGEST_TOKEN"\n')).runs

    assert (only.name, only.type, only.url, only.token_env) == ("cron", None, None, "CRON_INGEST_TOKEN")


def test_an_instance_with_neither_a_type_nor_a_token_is_refused(tmp_path: Path) -> None:
    assert _refusal(tmp_path, '[[runs]]\nname = "cron"\n') == "a runs instance needs type"


@pytest.mark.parametrize("given", ['type = "dagu"', 'url = "http://ci.test"'])
def test_a_push_only_instance_takes_neither_half_of_a_pull_adapter(tmp_path: Path, given: str) -> None:
    text = f'[[runs]]\nname = "cron"\ntoken_env = "CRON_INGEST_TOKEN"\n{given}\n'

    assert _refusal(tmp_path, text) == f"a runs instance needs {'url' if given.startswith('type') else 'type'}"


def test_a_push_only_instance_has_nothing_to_start_so_run_safe_is_refused(tmp_path: Path) -> None:
    text = '[[runs]]\nname = "cron"\ntoken_env = "CRON_INGEST_TOKEN"\nrun_safe = ["nightly"]\n'

    assert _refusal(tmp_path, text) == (
        "runs instance cron: a push-only instance has no start, so run_safe does not apply"
    )


def test_an_unknown_instance_key_is_refused_by_name_beside_the_known_ones(tmp_path: Path) -> None:
    text = '[[runs]]\nname = "ci"\ntype = "dagu"\nurl = "http://ci.test"\nrunsafe = []\nzeta = 1\n'

    assert _refusal(tmp_path, text) == (
        "runs instance ci: unknown key(s) runsafe, zeta; known: commit, domains, name, run_safe, token_env, type, url"
    )


def test_an_instance_type_that_names_no_adapter_is_refused(tmp_path: Path) -> None:
    text = '[[runs]]\nname = "ci"\ntype = "airflowz"\nurl = "http://ci.test"\n'

    assert _refusal(tmp_path, text) == "runs instance ci: no runs adapter of type airflowz"


def _adapter_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, package: str, module: str, source: str) -> None:
    """An installed-package stand-in: `<package>.<module>` importable from `tmp_path`."""
    (tmp_path / package).mkdir()
    (tmp_path / package / "__init__.py").touch()
    (tmp_path / package / f"{module}.py").write_text(source)
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in (package, f"{package}.{module}"):
        monkeypatch.delitem(sys.modules, name, raising=False)


def test_an_instance_type_may_be_the_dotted_path_of_a_module_outside_starpulse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _adapter_module(
        tmp_path, monkeypatch, "acme", "runs", "def start(url): return None\ndef follow(url, runs, log): ...\n"
    )
    text = '[[runs]]\nname = "ci"\ntype = "acme.runs"\nurl = "http://ci.test"\n'

    (only,) = load(_write(tmp_path, text)).runs

    assert (only.type, runs_adapter(only.type).__name__) == ("acme.runs", "acme.runs")


def test_a_dotted_type_that_resolves_but_is_no_runs_adapter_is_refused_naming_its_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _adapter_module(tmp_path, monkeypatch, "acme", "notruns", "def start(url): return None\n")
    text = '[[runs]]\nname = "ci"\ntype = "acme.notruns"\nurl = "http://ci.test"\n'

    assert _refusal(tmp_path, text) == (
        "runs instance ci: acme.notruns is not a runs adapter: it needs start(url) and follow(url, runs, log)"
    )


def test_a_dotted_type_whose_module_is_missing_is_refused(tmp_path: Path) -> None:
    text = '[[runs]]\nname = "ci"\ntype = "acme_absent.runs"\nurl = "http://ci.test"\n'

    assert _refusal(tmp_path, text) == "runs instance ci: no runs adapter of type acme_absent.runs"


def test_a_dotted_type_that_fails_to_import_is_refused_with_the_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _adapter_module(tmp_path, monkeypatch, "acme", "broken", "import acme_missing_dependency\n")
    text = '[[runs]]\nname = "ci"\ntype = "acme.broken"\nurl = "http://ci.test"\n'

    assert "acme_missing_dependency" in _refusal(tmp_path, text)


def test_hub_mode_is_a_serve_flag_not_a_config_setting(tmp_path: Path) -> None:
    assert _refusal(tmp_path, 'mode = "hub"\n') == (
        "mode 'hub' is not a config setting; use mode = \"ic\", and start a hub with `serve --hub`"
    )


def test_unknown_keys_are_refused_by_name_beside_the_known_ones(tmp_path: Path) -> None:
    assert _refusal(tmp_path, 'zeta = 1\ntrakcer_url = "http://x.test"\n') == (
        "unknown config key(s) trakcer_url, zeta; known: aggregates_only, board, ci, database_url, event_log_archive_dir, event_log_retention_days, "
        "forward, harnesses_file, hub_retention_days, level, mode, oidc, repos, runs, session_start_url, sources, tracker_url"
    )


@pytest.mark.parametrize("old", ['adapters = ["backlog"]', 'orchestrator_url = "http://x.test"', "run_safe = []"])
def test_the_single_orchestrator_keys_are_gone_in_favour_of_runs_instances(tmp_path: Path, old: str) -> None:
    assert "runs" in _refusal(tmp_path, old + "\n")


_HARNESSES = (
    'tiers = ["standard"]\n[harnesses.claude]\nsessions = true\n'
    '[harnesses.claude.tiers.standard]\nmodel = "sonnet"\nefforts = ["high"]\n'
)


def test_the_harness_file_is_read_from_beside_the_config(tmp_path: Path) -> None:
    (tmp_path / "harnesses.toml").write_text(_HARNESSES)

    config = load(_write(tmp_path, 'harnesses_file = "harnesses.toml"\n'))

    assert config.harnesses is not None
    assert config.harnesses.harnesses["claude"].profiles() == {"@agent-standard-high": ("sonnet", "high")}


def test_without_a_harness_file_no_harness_is_configured(tmp_path: Path) -> None:
    assert load(_write(tmp_path, "")).harnesses is None


def test_a_harness_file_that_is_not_there_is_refused_naming_it(tmp_path: Path) -> None:
    assert (
        _refusal(tmp_path, 'harnesses_file = "nope.toml"\n')
        == f"harnesses_file {tmp_path / 'nope.toml'} does not exist"
    )


def test_a_harness_file_the_view_cannot_use_is_refused_with_its_reason(tmp_path: Path) -> None:
    (tmp_path / "harnesses.toml").write_text("tiers = []\n")

    with pytest.raises(HarnessError, match="tiers must be a non-empty list of names"):
        load(_write(tmp_path, 'harnesses_file = "harnesses.toml"\n'))


@pytest.mark.parametrize("text", ["runs = 3\n", "runs = [3]\n"])
def test_runs_that_are_not_a_list_of_tables_are_refused(tmp_path: Path, text: str) -> None:
    assert _refusal(tmp_path, text) == "runs must be a list of [[runs]] tables"


def test_an_instance_type_that_is_not_text_is_refused(tmp_path: Path) -> None:
    text = '[[runs]]\nname = "ci"\ntype = 3\nurl = "http://ci.test"\n'

    assert _refusal(tmp_path, text) == "runs instance ci: no runs adapter of type 3"


def test_an_instance_url_that_is_not_text_is_refused(tmp_path: Path) -> None:
    text = '[[runs]]\nname = "ci"\ntype = "dagu"\nurl = 3\n'

    assert _refusal(tmp_path, text) == "runs instance ci: url must be text"


def test_the_session_start_service_is_reached_at_the_address_the_config_names(tmp_path: Path) -> None:
    config = load(_write(tmp_path, 'session_start_url = "http://sessions.example.test:6422"\n'))

    assert config.session_start_url == "http://sessions.example.test:6422"


def test_without_a_session_start_address_no_session_can_be_started() -> None:
    assert load(None).session_start_url is None


def test_a_session_start_address_that_is_not_text_is_refused(tmp_path: Path) -> None:
    assert _refusal(tmp_path, "session_start_url = 6422\n") == "session_start_url must be text"


@pytest.mark.parametrize(
    ("text", "refusal"),
    [
        ('board = "backlog"\n', "board must be a [board] table"),
        ("[board]\ntype = 3\n", "board type 3 is not a module name"),
        ('[board]\ntype = "a b"\n', "board type 'a b' is not a module name"),
        ('[board]\ntype = "starpulse.no-such"\n', "board type 'starpulse.no-such' is not a module name"),
        ("database_url = 5\n", "database_url must be text"),
    ],
)
def test_a_board_or_database_setting_of_the_wrong_shape_is_refused(tmp_path: Path, text: str, refusal: str) -> None:
    assert _refusal(tmp_path, text) == refusal


def test_an_instance_names_the_environment_variable_that_holds_its_ingest_token(tmp_path: Path) -> None:
    text = '[[runs]]\nname = "cron"\ntype = "dagu"\nurl = "http://cron.test"\ntoken_env = "CRON_INGEST_TOKEN"\n'

    (cron,) = load(_write(tmp_path, text)).runs

    assert cron.token_env == "CRON_INGEST_TOKEN"


def test_an_instance_with_no_token_env_takes_no_pushed_events(tmp_path: Path) -> None:
    (prod, _) = load(_write(tmp_path, _TWO_INSTANCES)).runs

    assert prod.token_env is None


@pytest.mark.parametrize("value", ["1", '""', '"has space"', '"9LIVES"', "[]"])
def test_a_token_env_that_is_not_an_environment_variable_name_is_refused(tmp_path: Path, value: str) -> None:
    text = f'[[runs]]\nname = "cron"\ntype = "dagu"\nurl = "http://cron.test"\ntoken_env = {value}\n'

    assert _refusal(tmp_path, text) == "runs instance cron: token_env must be the name of an environment variable"


def test_two_instances_cannot_share_a_token_env(tmp_path: Path) -> None:
    one = '[[runs]]\nname = "{}"\ntype = "dagu"\nurl = "http://x.test"\ntoken_env = "SHARED"\n'
    text = one.format("a") + one.format("b")

    assert _refusal(tmp_path, text) == "runs instances a and b share token_env SHARED; each needs its own token"


def test_a_hub_keeps_two_weeks_of_raw_events_unless_the_config_says_otherwise(tmp_path: Path) -> None:
    assert load(None).hub_retention_days == 14
    assert load(_write(tmp_path, "hub_retention_days = 30\n")).hub_retention_days == 30


@pytest.mark.parametrize("value", ["0", "-3", "1.5", '"14"', "true"])
def test_a_hub_retention_that_is_not_a_positive_whole_number_of_days_is_refused(tmp_path: Path, value: str) -> None:
    assert (
        _refusal(tmp_path, f"hub_retention_days = {value}\n")
        == "hub_retention_days must be a whole number of days, 1 or more"
    )


_OIDC = """
[oidc]
issuer = "https://id.example.test/realm"
client_id = "starpulse-hub"
client_secret_env = "HUB_OIDC_SECRET"
redirect_uri = "https://hub.example.test/auth/callback"
allowed_groups = ["flow-viewers", "ops"]
"""


def test_an_oidc_table_names_the_issuer_the_client_and_the_allowed_groups(tmp_path: Path) -> None:
    config = load(_write(tmp_path, _OIDC))

    assert config.oidc == OidcSettings(
        issuer="https://id.example.test/realm",
        client_id="starpulse-hub",
        client_secret_env="HUB_OIDC_SECRET",
        redirect_uri="https://hub.example.test/auth/callback",
        allowed_groups=("flow-viewers", "ops"),
    )
    assert (config.oidc.groups_claim, config.oidc.scopes, config.oidc.engine_token_env) == (
        "groups",
        ("openid", "profile", "email"),
        None,
    )


def test_an_oidc_table_may_set_the_groups_claim_the_scopes_and_the_engine_token_variable(tmp_path: Path) -> None:
    extra = 'groups_claim = "roles"\nscopes = ["openid", "roles"]\nengine_token_env = "HUB_ENGINE_TOKEN"\n'
    oidc = load(_write(tmp_path, _OIDC + extra)).oidc

    assert oidc is not None
    assert (oidc.groups_claim, oidc.scopes, oidc.engine_token_env) == ("roles", ("openid", "roles"), "HUB_ENGINE_TOKEN")


def test_an_oidc_table_may_name_the_reader_token_variable(tmp_path: Path) -> None:
    oidc = load(_write(tmp_path, _OIDC + 'reader_token_env = "STARPULSE_TOKEN"\n')).oidc

    assert oidc is not None
    assert oidc.reader_token_env == "STARPULSE_TOKEN"
    assert load(_write(tmp_path, _OIDC)).oidc.reader_token_env is None  # type: ignore[union-attr]


def test_a_reader_token_variable_that_is_no_variable_name_is_refused(tmp_path: Path) -> None:
    refused = _refusal(tmp_path, _OIDC + 'reader_token_env = "has space"\n')

    assert refused == "oidc: reader_token_env must be the name of an environment variable"


def test_a_config_without_an_oidc_table_has_none() -> None:
    assert load(None).oidc is None


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        ('issuer = "https://id.example.test/realm"\n', "oidc: issuer is required"),
        ('client_id = "starpulse-hub"\n', "oidc: client_id is required"),
        ('client_secret_env = "HUB_OIDC_SECRET"\n', "oidc: client_secret_env is required"),
        ('redirect_uri = "https://hub.example.test/auth/callback"\n', "oidc: redirect_uri is required"),
        ('allowed_groups = ["flow-viewers", "ops"]\n', "oidc: allowed_groups must name at least one group"),
    ],
)
def test_an_oidc_table_missing_a_required_key_is_refused(tmp_path: Path, edit: str, message: str) -> None:
    assert _refusal(tmp_path, _OIDC.replace(edit, "")) == message


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            'allowed_groups = ["flow-viewers", "ops"]',
            "allowed_groups = []",
            "oidc: allowed_groups must name at least one group",
        ),
        (
            'allowed_groups = ["flow-viewers", "ops"]',
            'allowed_groups = "ops"',
            "oidc: allowed_groups must name at least one group",
        ),
        (
            'allowed_groups = ["flow-viewers", "ops"]',
            'allowed_groups = [""]',
            "oidc: allowed_groups must name at least one group",
        ),
        ('"HUB_OIDC_SECRET"', '"has space"', "oidc: client_secret_env must be the name of an environment variable"),
        ('"https://id.example.test/realm"', '"id.example.test"', "oidc: issuer must be an http(s) URL"),
        ('"https://hub.example.test/auth/callback"', '"/auth/callback"', "oidc: redirect_uri must be an http(s) URL"),
        ('client_id = "starpulse-hub"', "client_id = 3", "oidc: client_id must be text"),
    ],
)
def test_an_oidc_table_with_a_bad_value_is_refused(tmp_path: Path, old: str, new: str, message: str) -> None:
    assert _refusal(tmp_path, _OIDC.replace(old, new)) == message


def test_an_oidc_table_with_an_unknown_key_is_refused(tmp_path: Path) -> None:
    assert _refusal(tmp_path, _OIDC + "color = 1\n") == "oidc: unknown key(s) color"


def test_oidc_is_a_table(tmp_path: Path) -> None:
    assert _refusal(tmp_path, "oidc = 3\n") == "oidc must be an [oidc] table"


def test_a_forward_table_names_the_hub_its_token_variable_and_a_default_batch(tmp_path: Path) -> None:
    text = '[forward]\nurl = "https://hub.example.test"\ntoken_env = "HUB_TOKEN"\n'

    forward = load(_write(tmp_path, text)).forward

    assert forward == Forward(url="https://hub.example.test", token_env="HUB_TOKEN", batch=50)


def test_no_forward_table_means_nothing_is_forwarded(tmp_path: Path) -> None:
    assert load(None).forward is None
    assert load(_write(tmp_path, 'tracker_url = "http://t.test"\n')).forward is None


@pytest.mark.parametrize(
    ("table", "reason"),
    [
        ('token_env = "T"', "forward needs url"),
        ('url = "https://hub.test"', "forward needs token_env"),
        ('url = "hub.test"\ntoken_env = "T"', "forward url must be an http:// or https:// address"),
        ('url = "https://hub.test"\ntoken_env = "not a name"', "forward token_env must be the name of an environment variable"),
        ('url = "https://hub.test"\ntoken_env = "T"\nbatch = 0', "forward batch must be a whole number from 1 to 200"),
        ('url = "https://hub.test"\ntoken_env = "T"\nbatch = 201', "forward batch must be a whole number from 1 to 200"),
        ('url = "https://hub.test"\ntoken_env = "T"\nbatch = true', "forward batch must be a whole number from 1 to 200"),
        ('url = "https://hub.test"\ntoken_env = "T"\nopt_in = true', "forward: unknown key(s) opt_in; known: batch, token_env, url"),
    ],
)
def test_a_forward_table_that_cannot_run_is_refused_with_its_reason(tmp_path: Path, table: str, reason: str) -> None:
    assert _refusal(tmp_path, f"[forward]\n{table}\n") == reason


def test_sources_are_the_instances_a_hub_accepts_events_from_each_with_its_own_token_variable(tmp_path: Path) -> None:
    text = (
        '[[sources]]\nname = "ana"\ntoken_env = "ANA_TOKEN"\n\n[[sources]]\nname = "bo"\ntoken_env = "BO_TOKEN"\n'
    )

    config = load(_write(tmp_path, text))

    assert config.sources == (Source("ana", "ANA_TOKEN"), Source("bo", "BO_TOKEN"))


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ('[[sources]]\ntoken_env = "T"\n', "a source needs name"),
        ('[[sources]]\nname = "ana"\n', "a source needs token_env"),
        ('[[sources]]\nname = "a/b"\ntoken_env = "T"\n', "source names must be non-empty text without a /"),
        ('[[sources]]\nname = "ana"\ntoken_env = "T 1"\n', "source ana: token_env must be the name of an environment variable"),
        ('[[sources]]\nname = "ana"\ntoken_env = "T"\nurl = "x"\n', "source ana: unknown key(s) url; known: name, token_env"),
        (
            '[[sources]]\nname = "ana"\ntoken_env = "A"\n[[sources]]\nname = "ana"\ntoken_env = "B"\n',
            "source ana is configured twice",
        ),
        (
            '[[sources]]\nname = "ana"\ntoken_env = "A"\n[[sources]]\nname = "bo"\ntoken_env = "A"\n',
            "sources ana and bo share token_env A; each needs its own token",
        ),
    ],
)
def test_a_sources_table_that_cannot_run_is_refused_with_its_reason(tmp_path: Path, text: str, reason: str) -> None:
    assert _refusal(tmp_path, text) == reason


def test_a_hub_takes_names_unless_it_is_configured_for_aggregates_only(tmp_path: Path) -> None:
    assert load(None).aggregates_only is False
    assert load(_write(tmp_path, "aggregates_only = true\n")).aggregates_only is True
    assert _refusal(tmp_path, 'aggregates_only = "yes"\n') == "aggregates_only must be true or false"


def test_the_event_log_keeps_seven_days_unless_the_config_says_otherwise(tmp_path: Path) -> None:
    assert load(_write(tmp_path, "")).event_log_retention_days == 7
    assert load(_write(tmp_path, "event_log_retention_days = 30\n")).event_log_retention_days == 30


def test_the_event_log_archive_is_a_directory_beside_the_config_unless_the_config_names_one(tmp_path: Path) -> None:
    assert load(None).event_log_archive_dir == "starpulse-archive"
    assert load(_write(tmp_path, 'event_log_archive_dir = "/mnt/history"\n')).event_log_archive_dir == "/mnt/history"


@pytest.mark.parametrize("value", ["7", "true", '""'])
def test_an_event_log_archive_dir_that_is_not_a_path_is_refused(tmp_path: Path, value: str) -> None:
    assert _refusal(tmp_path, f"event_log_archive_dir = {value}\n") == "event_log_archive_dir must be a directory path"


@pytest.mark.parametrize("value", ["0", "-3", "1.5", "true", '"7"'])
def test_an_event_log_retention_that_is_not_a_whole_number_of_days_is_refused(tmp_path: Path, value: str) -> None:
    assert "event_log_retention_days must be a whole number of days, 1 or more" in _refusal(
        tmp_path, f"event_log_retention_days = {value}\n"
    )


_DAGU = '[[runs]]\nname = "dagu"\ntype = "dagu"\nurl = "http://dagu.test"\n'


def test_an_instance_maps_commit_keys_onto_the_run_parameters_that_carry_them(tmp_path: Path) -> None:
    text = _DAGU + '[runs.commit]\nafter = "AFTER"\nbefore = "BEFORE"\nforce = "FORCE"\ntask = "TASK"\n'

    (dagu,) = load(_write(tmp_path, text)).runs

    assert dagu.commit == CommitKeys(after="AFTER", before="BEFORE", force="FORCE", task="TASK")


def test_an_instance_may_declare_only_some_commit_keys(tmp_path: Path) -> None:
    (dagu,) = load(_write(tmp_path, _DAGU + '[runs.commit]\nafter = "SHA"\n')).runs

    assert dagu.commit == CommitKeys(after="SHA")


def test_an_instance_with_no_commit_table_pairs_its_runs_by_time(tmp_path: Path) -> None:
    (dagu,) = load(_write(tmp_path, _DAGU)).runs

    assert dagu.commit is None


@pytest.mark.parametrize("value", ["1", '""', '"has space"', "[]"])
def test_a_commit_key_that_is_not_a_parameter_name_is_refused(tmp_path: Path, value: str) -> None:
    text = _DAGU + f"[runs.commit]\nafter = {value}\n"

    assert _refusal(tmp_path, text) == "runs instance dagu: commit.after must be the name of a run parameter"


def test_an_unknown_commit_key_is_refused_beside_the_known_ones(tmp_path: Path) -> None:
    text = _DAGU + '[runs.commit]\nafter = "AFTER"\nsha = "SHA"\n'

    assert _refusal(tmp_path, text) == (
        "runs instance dagu: commit: unknown key(s) sha; known: after, before, force, task"
    )


def test_a_commit_that_is_not_a_table_is_refused(tmp_path: Path) -> None:
    assert _refusal(tmp_path, _DAGU.replace("[[runs]]\n", "[[runs]]\ncommit = 1\n")) == (
        "runs instance dagu: commit must be a [runs.commit] table"
    )


def test_a_repos_table_names_a_repository_whose_merges_apply_through_the_parents_pin_bump(tmp_path: Path) -> None:
    text = '[[repos]]\nname = "starpulse"\npath = "starpulse"\napplied_by = "pin-bump"\n'

    assert load(_write(tmp_path, text)).repos == (Repo(name="starpulse", path="starpulse", applied_by="pin-bump"),)


def test_a_config_with_no_repos_table_declares_no_pin_bump_repository(tmp_path: Path) -> None:
    assert load(_write(tmp_path, "")).repos == ()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[[repos]]\nname = "a"\npath = "a"\napplied_by = "rsync"\n', "applied_by must be pin-bump"),
        ('[[repos]]\nname = "a"\npath = "a"\n', "a repos entry needs applied_by"),
        ('[[repos]]\nname = "a"\npath = "../a"\napplied_by = "pin-bump"\n', "path must be a relative path inside"),
        ('[[repos]]\nname = "a"\npath = "a"\napplied_by = "pin-bump"\nurl = "x"\n', "unknown key(s) url"),
        ('[[repos]]\nname = "a/b"\npath = "a"\napplied_by = "pin-bump"\n', "names must be non-empty text without a /"),
        (
            '[[repos]]\nname = "a"\npath = "a"\napplied_by = "pin-bump"\n'
            '[[repos]]\nname = "a"\npath = "b"\napplied_by = "pin-bump"\n',
            "repos entry a is configured twice",
        ),
    ],
)
def test_a_repos_entry_the_loader_cannot_use_is_refused_with_the_key_to_fix(
    tmp_path: Path, text: str, message: str
) -> None:
    assert message in _refusal(tmp_path, text)
