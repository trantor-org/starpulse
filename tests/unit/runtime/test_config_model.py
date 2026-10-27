"""The config models declare what `config.load` accepts, and the settings reference in `docs/serving.md` is their schema."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from starpulse.runtime import config_reference
from starpulse.runtime.config import ConfigError, load
from starpulse.runtime.config_model import ConfigFile
from starpulse.runtime.config_reference import DOC, render


def _loads(tmp_path: Path, text: str) -> bool:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    try:
        load(path)
    except ConfigError:
        return False
    return True


#: A setting the models constrain and one value past the constraint, as the loader refuses it too.
REFUSED = [
    ("event_log_retention_days = 0\n", {"event_log_retention_days": 0}),
    ("slow_read_seconds = 0\n", {"slow_read_seconds": 0}),
    ('event_log_archive_dir = ""\n', {"event_log_archive_dir": ""}),
    ("take_over_command = []\n", {"take_over_command": []}),
    ('refresh_token_env = "not a name"\n', {"refresh_token_env": "not a name"}),
    ('mode = "team"\n', {"mode": "team"}),
    ("[worker_memory.pulls]\nsoft_mb = 0\n", {"worker_memory": {"pulls": {"soft_mb": 0}}}),
    ("[worker_memory.nowhere]\nsoft_mb = 1\n", {"worker_memory": {"nowhere": {"soft_mb": 1}}}),
    (
        '[[repos]]\nname = "a"\npath = "a"\napplied_by = "merge"\n',
        {"repos": [{"name": "a", "path": "a", "applied_by": "merge"}]},
    ),
    ('[[producers]]\nname = "a/b"\ntoken_env = "T"\n', {"producers": [{"name": "a/b", "token_env": "T"}]}),
    (
        '[[producers]]\nname = "a"\ntoken_env = "T"\nextra = 1\n',
        {"producers": [{"name": "a", "token_env": "T", "extra": 1}]},
    ),
    ("[ci]\nstates = []\n", {"ci": {"states": []}}),
    ('[release]\nsettle = "never"\n', {"release": {"settle": "never"}}),
]


@pytest.mark.parametrize(("toml", "data"), REFUSED)
def test_a_value_the_models_refuse_is_one_the_loader_refuses(tmp_path: Path, toml: str, data: dict) -> None:
    with pytest.raises(ValidationError):
        ConfigFile.model_validate(data)
    assert not _loads(tmp_path, toml)


def test_a_key_the_models_declare_is_one_the_loader_accepts(tmp_path: Path) -> None:
    assert ConfigFile.model_validate({"event_log_retention_days": 30, "pull_requests": False})
    assert _loads(tmp_path, "event_log_retention_days = 30\npull_requests = false\n")


def test_a_key_the_models_do_not_declare_is_refused_by_both(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ConfigFile.model_validate({"trakcer_url": "x"})
    assert not _loads(tmp_path, 'trakcer_url = "x"\n')


def test_the_settings_reference_in_the_serving_doc_is_current() -> None:
    text = DOC.read_text()

    assert render(text) == text, "run `python -m starpulse.runtime.config_reference` and commit docs/serving.md"


def test_every_setting_has_a_description() -> None:
    schema = ConfigFile.model_json_schema()
    tables = [schema, *schema["$defs"].values()]

    missing = [
        (table["title"], key)
        for table in tables
        for key, node in table["properties"].items()
        if not node.get("description")
    ]

    assert missing == []


def test_the_reference_names_every_table_and_top_level_key() -> None:
    reference = config_reference.reference()

    for heading in ("Top level", "[[runs]]", "[runs.commit]", "[[producers]]", "[[repos]]", "[release]", "[ci]"):
        assert f"#### {heading}\n" in reference
    assert all(f"- `{key}` (" in reference for key in ConfigFile.model_fields)
