"""StarPulse's one config file: where its tracker and orchestrator are and which adapters run."""

import sys
from pathlib import Path

import pytest
from starpulse.board.model.commit_keys import CommitKeys
from starpulse.harness_telemetry.harnesses import HarnessError
from starpulse.pulls.pins import Repo
from starpulse.runs.config import Producer
from starpulse.runtime.config import Config, ConfigError, MemoryLimit, load, runs_adapter


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "starpulse.toml"
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


def test_an_instance_with_no_type_is_refused(tmp_path: Path) -> None:
    assert _refusal(tmp_path, '[[runs]]\nname = "cron"\n') == "a runs instance needs type"


def test_a_token_env_on_an_instance_is_an_unknown_key(tmp_path: Path) -> None:
    text = '[[runs]]\nname = "cron"\ntype = "dagu"\nurl = "http://ci.test"\ntoken_env = "CRON_INGEST_TOKEN"\n'

    assert "unknown key(s) token_env" in _refusal(tmp_path, text)


def test_an_unknown_instance_key_is_refused_by_name_beside_the_known_ones(tmp_path: Path) -> None:
    text = '[[runs]]\nname = "ci"\ntype = "dagu"\nurl = "http://ci.test"\nrunsafe = []\nzeta = 1\n'

    assert _refusal(tmp_path, text) == (
        "runs instance ci: unknown key(s) runsafe, zeta; known: commit, domains, name, run_safe, type, url"
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


def test_a_mode_other_than_ic_is_not_a_config_setting(tmp_path: Path) -> None:
    assert _refusal(tmp_path, 'mode = "team"\n') == "mode 'team' is not a config setting; use mode = \"ic\""


def test_unknown_keys_are_refused_by_name_beside_the_known_ones(tmp_path: Path) -> None:
    assert _refusal(tmp_path, 'zeta = 1\ntrakcer_url = "http://x.test"\n') == (
        "unknown config key(s) trakcer_url, zeta; known: analytics, api_worker, board, board_worker, ci, cursor_context, database_url, event_log_archive_dir, event_log_retention_days, "
        "flow_metrics_worker, harnesses_file, level, mode, producers, project, pull_requests, read_model, refresh_token_env, release, repos, runs, runs_worker, scheduler, search, search_worker, session_start_url, slow_read_seconds, take_over_command, tls_cert, tls_key, tracker_url, worker_memory"
    )


def test_a_triggers_table_is_refused_by_name_as_a_removed_table(tmp_path: Path) -> None:
    refusal = _refusal(tmp_path, '[[triggers]]\non = "lane"\nstart = "dagu/review-run"\n')

    assert refusal == "[[triggers]] removed in 0.4: start runs from your orchestrator"


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


def test_producers_are_the_systems_that_post_machine_events_each_with_its_token_variable_machines_and_actors(
    tmp_path: Path,
) -> None:
    text = (
        '[[producers]]\nname = "dagu"\ntoken_env = "DAGU_TOKEN"\nmachines = ["board", "ci"]\nactors = ["dagu/nightly"]\n\n'
        '[[producers]]\nname = "gha"\ntoken_env = "GHA_TOKEN"\nmachines = ["ci"]\nactors = ["ci"]\n'
    )

    config = load(_write(tmp_path, text))

    assert config.producers == (
        Producer("dagu", "DAGU_TOKEN", ("board", "ci"), ("dagu/nightly",)),
        Producer("gha", "GHA_TOKEN", ("ci",), ("ci",)),
    )
    assert load(None).producers == ()


def test_a_producer_that_lists_no_machines_or_actors__is_still_a_producer(tmp_path: Path) -> None:
    config_file = tmp_path / "starpulse.toml"
    config_file.write_text('[[producers]]\nname = "cron"\ntoken_env = "CRON_TOKEN"\n')

    (producer,) = load(config_file).producers

    assert (producer.name, producer.machines, producer.actors) == ("cron", (), ())


_PRODUCER = 'name = "dagu"\ntoken_env = "T"\nmachines = ["ci"]\nactors = ["ci"]\n'


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ('[[producers]]\ntoken_env = "T"\nmachines = ["ci"]\nactors = ["ci"]\n', "a producer needs name"),
        ('[[producers]]\nname = "d"\nmachines = ["ci"]\nactors = ["ci"]\n', "a producer needs token_env"),
        (
            '[[producers]]\nname = "a/b"\ntoken_env = "T"\nmachines = ["ci"]\nactors = ["ci"]\n',
            "producer names must be non-empty text without a /",
        ),
        (
            '[[producers]]\nname = "d"\ntoken_env = "T 1"\nmachines = ["ci"]\nactors = ["ci"]\n',
            "producer d: token_env must be the name of an environment variable",
        ),
        (
            '[[producers]]\nname = "d"\ntoken_env = "T"\nmachines = []\nactors = ["ci"]\n',
            "producer d: machines must be a non-empty list of text",
        ),
        (
            '[[producers]]\nname = "d"\ntoken_env = "T"\nmachines = ["ci"]\nactors = [1]\n',
            "producer d: actors must be a non-empty list of text",
        ),
        (
            "[[producers]]\n" + _PRODUCER + 'url = "x"\n',
            "producer dagu: unknown key(s) url; known: actors, machines, name, token_env",
        ),
        (
            "[[producers]]\n"
            + _PRODUCER
            + '[[producers]]\nname = "dagu"\ntoken_env = "U"\nmachines = ["ci"]\nactors = ["ci"]\n',
            "producer dagu is configured twice",
        ),
        (
            "[[producers]]\n"
            + _PRODUCER
            + '[[producers]]\nname = "gha"\ntoken_env = "T"\nmachines = ["ci"]\nactors = ["ci"]\n',
            "producers dagu and gha share token_env T; each needs its own token",
        ),
        ("producers = 1\n", "producers must be a list of [[producers]] tables"),
    ],
)
def test_a_producers_table_that_cannot_run_is_refused_with_its_reason(tmp_path: Path, text: str, reason: str) -> None:
    assert _refusal(tmp_path, text) == reason


def test_the_pull_request_refresh_credential_is_the_name_of_an_environment_variable(tmp_path: Path) -> None:
    assert load(None).refresh_token_env is None
    assert load(_write(tmp_path, 'refresh_token_env = "PULLS_TOKEN"\n')).refresh_token_env == "PULLS_TOKEN"
    assert _refusal(tmp_path, 'refresh_token_env = "not a name"\n') == (
        "refresh_token_env must be the name of an environment variable"
    )


def test_the_take_over_command_is_an_argv_of_strings(tmp_path: Path) -> None:
    assert load(None).take_over_command is None
    assert load(_write(tmp_path, 'take_over_command = ["take-over", "--engine"]\n')).take_over_command == (
        "take-over",
        "--engine",
    )
    for text in ('take_over_command = "take-over"\n', "take_over_command = []\n", 'take_over_command = ["a", 1]\n'):
        assert _refusal(tmp_path, text) == "take_over_command must be a non-empty list of strings"


def test_an_instance_keeps_a_pull_request_store_unless_configured_off(tmp_path: Path) -> None:
    assert load(None).pull_requests is True
    assert load(_write(tmp_path, "pull_requests = false\n")).pull_requests is False
    assert _refusal(tmp_path, 'pull_requests = "no"\n') == "pull_requests must be true or false"


@pytest.mark.parametrize("context", ["delivery", "scheduler"])
def test_a_removed_worker_setting_is_refused_by_name(tmp_path: Path, context: str) -> None:
    key = f"{context}_worker"
    assert _refusal(tmp_path, f"{key} = true\n").startswith(f"unknown config key(s) {key};")


def test_runs_worker_defaults_off_and_is_a_flag(tmp_path: Path) -> None:
    assert load(None).runs_worker is False
    assert load(_write(tmp_path, "runs_worker = true\n")).runs_worker is True
    assert _refusal(tmp_path, 'runs_worker = "yes"\n') == "runs_worker must be true or false"


def test_flow_metrics_worker_defaults_off_and_is_a_flag(tmp_path: Path) -> None:
    assert load(None).flow_metrics_worker is False
    assert load(_write(tmp_path, "flow_metrics_worker = true\n")).flow_metrics_worker is True
    assert _refusal(tmp_path, 'flow_metrics_worker = "yes"\n') == "flow_metrics_worker must be true or false"


def test_history_worker_key_is_refused_as_unknown(tmp_path: Path) -> None:
    assert "history_worker" in _refusal(tmp_path, "history_worker = true\n")


@pytest.mark.parametrize("key", ["flow_metrics", "history"])
def test_worker_memory_retired_spellings_are_refused_as_unknown(tmp_path: Path, key: str) -> None:
    assert key in _refusal(tmp_path, f"[worker_memory.{key}]\nsoft_mb = 10\nhard_mb = 20\n")
    tuned = load(_write(tmp_path, "[worker_memory.flow-metrics]\nsoft_mb = 10\nhard_mb = 20\n")).worker_memory
    assert tuned["flow-metrics"] == MemoryLimit(10, 20)


def test_board_worker_defaults_off_and_is_a_flag(tmp_path: Path) -> None:
    assert load(None).board_worker is False
    assert load(_write(tmp_path, "board_worker = true\n")).board_worker is True
    assert _refusal(tmp_path, 'board_worker = "yes"\n') == "board_worker must be true or false"


def test_the_retired_read_model_key_still_loads_and_sets_nothing(tmp_path: Path) -> None:
    assert not hasattr(load(_write(tmp_path, "read_model = true\n")), "read_model")


def test_search_worker_defaults_off_and_is_a_flag(tmp_path: Path) -> None:
    assert load(None).search_worker is False
    assert load(_write(tmp_path, "search_worker = true\n")).search_worker is True
    assert _refusal(tmp_path, 'search_worker = "yes"\n') == "search_worker must be true or false"


def test_a_pulls_read_is_slow_at_one_second_unless_the_config_says_otherwise(tmp_path: Path) -> None:
    assert load(None).slow_read_seconds == 1.0
    assert load(_write(tmp_path, "slow_read_seconds = 0.25\n")).slow_read_seconds == 0.25
    assert load(_write(tmp_path, "slow_read_seconds = 3\n")).slow_read_seconds == 3.0


@pytest.mark.parametrize("value", ["0", "-1", "true", '"1"'])
def test_a_slow_read_threshold_that_is_not_a_positive_number_is_refused(tmp_path: Path, value: str) -> None:
    assert (
        _refusal(tmp_path, f"slow_read_seconds = {value}\n") == "slow_read_seconds must be a number of seconds above 0"
    )


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


_DAGU = '[[runs]]\nname = "dagu"\ntype = "dagu"\nurl = "http://dagu.test"\n'


def test_nested_domains_parse_into_flat_union_and_processes(tmp_path: Path) -> None:
    text = (
        _DAGU
        + '[runs.domains."Delivery & CI"]\n"CI gates" = ["ci-sp-web", "ci-validate"]\n"Merge apply" = ["apply-on-merge"]\n'
    )
    config = load(_write(tmp_path, text))
    (inst,) = config.runs
    assert inst.domains == {"Delivery & CI": ("apply-on-merge", "ci-sp-web", "ci-validate")}
    assert inst.processes == {
        "Delivery & CI": (("CI gates", ("ci-sp-web", "ci-validate")), ("Merge apply", ("apply-on-merge",)))
    }
    assert config.qualified_processes() == {
        "Delivery & CI": (
            ("CI gates", ("dagu/ci-sp-web", "dagu/ci-validate")),
            ("Merge apply", ("dagu/apply-on-merge",)),
        )
    }


def test_flat_domains_leave_processes_empty_and_keep_order(tmp_path: Path) -> None:
    (inst,) = load(_write(tmp_path, _DAGU + '[runs.domains]\nOps = ["nightly", "backup"]\n')).runs
    assert inst.domains == {"Ops": ("nightly", "backup")}
    assert inst.processes == {"Ops": ()}


def test_duplicate_workflow_in_two_processes_is_refused(tmp_path: Path) -> None:
    text = _DAGU + '[runs.domains.Ops]\nA = ["nightly"]\nB = ["nightly"]\n'
    refusal = _refusal(tmp_path, text)
    assert "duplicate" in refusal and "runs instance dagu" in refusal


def test_each_worker_context_has_a_packaged_memory_limit_that_the_config_overrides_per_key(tmp_path: Path) -> None:
    packaged = load(None).worker_memory
    text = "[worker_memory.pulls]\nsoft_mb = 100\n[worker_memory.scheduler]\nsoft_mb = 10\nhard_mb = 20\n"
    tuned = load(_write(tmp_path, text)).worker_memory

    assert set(packaged) == {"pulls", "scheduler", "runs", "flow-metrics", "search", "board"}
    assert all(0 < limit.soft_mb < limit.hard_mb for limit in packaged.values())
    assert tuned["pulls"] == MemoryLimit(100, packaged["pulls"].hard_mb)
    assert tuned["scheduler"] == MemoryLimit(10, 20)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "[worker_memory.pulss]\nsoft_mb = 1\n",
            "worker_memory: unknown context(s) pulss; known: board, flow-metrics, pulls, runs, scheduler, search",
        ),
        ("[worker_memory.pulls]\nsoft_mb = 900\nhard_mb = 900\n", "worker_memory.pulls: soft_mb must be below hard_mb"),
        ("[worker_memory.pulls]\nsoft_mb = 5000\n", "worker_memory.pulls: soft_mb must be below hard_mb"),
        (
            "[worker_memory.pulls]\nhard_mb = 0\n",
            "worker_memory.pulls: hard_mb must be a whole number of megabytes, 1 or more",
        ),
        ("[worker_memory.pulls]\nsoftmb = 1\n", "worker_memory.pulls: unknown key(s) softmb; known: hard_mb, soft_mb"),
        ("worker_memory = 3\n", "worker_memory must be a table of per-context tables"),
    ],
)
def test_a_worker_memory_table_naming_no_context_or_with_soft_at_or_above_hard_is_refused_by_name(
    tmp_path: Path, text: str, message: str
) -> None:
    assert _refusal(tmp_path, text) == message


def test_a_certificate_and_key_are_read_from_beside_the_config(tmp_path: Path) -> None:
    (tmp_path / "cert.pem").write_text("cert")
    (tmp_path / "key.pem").write_text("key")

    config = load(_write(tmp_path, 'tls_cert = "cert.pem"\ntls_key = "key.pem"\n'))

    assert config.tls == (tmp_path / "cert.pem", tmp_path / "key.pem")


def test_without_a_certificate_the_server_is_cleartext(tmp_path: Path) -> None:
    assert load(_write(tmp_path, "")).tls is None


def test_a_certificate_without_its_key_or_a_key_without_its_certificate_is_refused(tmp_path: Path) -> None:
    refusal = "tls_cert and tls_key are set together"

    assert _refusal(tmp_path, 'tls_cert = "cert.pem"\n') == refusal
    assert _refusal(tmp_path, 'tls_key = "key.pem"\n') == refusal


def test_a_certificate_or_key_that_is_not_there_is_refused_naming_it(tmp_path: Path) -> None:
    (tmp_path / "cert.pem").write_text("cert")

    assert _refusal(tmp_path, 'tls_cert = "cert.pem"\ntls_key = "key.pem"\n') == (
        f"tls_key {tmp_path / 'key.pem'} does not exist"
    )
