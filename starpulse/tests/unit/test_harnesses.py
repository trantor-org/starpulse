"""The harness configuration: the tiers an agent profile names and the model each tier runs on a harness."""

from pathlib import Path

import pytest

from starpulse.harnesses import HarnessError, load_harnesses

_CLAUDE = """
tiers = ["fast", "standard", "deep"]

[harnesses.claude]
label = "Claude Code"
sessions = true

[harnesses.claude.tiers.fast]
model = "haiku"

[harnesses.claude.tiers.standard]
model = "sonnet"
efforts = ["medium", "high"]

[harnesses.claude.tiers.deep]
model = "opus"
efforts = ["medium", "high"]
"""


def _load(tmp_path: Path, text: str):
    path = tmp_path / "harnesses.toml"
    path.write_text(text)
    return load_harnesses(path)


def _refusal(tmp_path: Path, text: str) -> str:
    with pytest.raises(HarnessError) as raised:
        _load(tmp_path, text)
    return str(raised.value)


def test_a_harness_names_its_model_and_efforts_per_tier(tmp_path: Path) -> None:
    config = _load(tmp_path, _CLAUDE)

    claude = config.harnesses["claude"]
    assert (config.tiers, claude.label, claude.sessions) == (("fast", "standard", "deep"), "Claude Code", True)
    assert [(t, claude.tiers[t].model, claude.tiers[t].efforts) for t in config.tiers] == [
        ("fast", "haiku", ()),
        ("standard", "sonnet", ("medium", "high")),
        ("deep", "opus", ("medium", "high")),
    ]


def test_a_harness_resolves_each_tier_profile_to_its_model_and_effort(tmp_path: Path) -> None:
    claude = _load(tmp_path, _CLAUDE).harnesses["claude"]

    assert claude.profiles() == {
        "@agent-fast": ("haiku", None),
        "@agent-standard-medium": ("sonnet", "medium"),
        "@agent-standard-high": ("sonnet", "high"),
        "@agent-deep-medium": ("opus", "medium"),
        "@agent-deep-high": ("opus", "high"),
    }


def test_the_page_receives_the_tiers_and_each_harness_without_its_credentials_or_paths(tmp_path: Path) -> None:
    assert _load(tmp_path, _CLAUDE).as_json() == {
        "tiers": ["fast", "standard", "deep"],
        "harnesses": [
            {
                "name": "claude",
                "label": "Claude Code",
                "sessions": True,
                "reason": None,
                "tiers": {
                    "fast": {"model": "haiku", "efforts": []},
                    "standard": {"model": "sonnet", "efforts": ["medium", "high"]},
                    "deep": {"model": "opus", "efforts": ["medium", "high"]},
                },
            }
        ],
    }


def test_a_harness_that_cannot_start_a_session_says_why(tmp_path: Path) -> None:
    text = (
        _CLAUDE
        + '\n[harnesses.codex]\nsessions = false\nreason = "no session-start path"\n'
        + "".join(f'\n[harnesses.codex.tiers.{t}]\nmodel = "m-{t}"\n' for t in ("fast", "standard", "deep"))
    )

    codex = _load(tmp_path, text).harnesses["codex"]

    assert (codex.sessions, codex.reason) == (False, "no session-start path")


def test_a_harness_without_a_session_path_must_give_a_reason(tmp_path: Path) -> None:
    text = _CLAUDE.replace("sessions = true", "sessions = false")

    assert _refusal(tmp_path, text) == "harness claude cannot start a session, so it needs a reason"


def test_a_harness_must_cover_exactly_the_declared_tiers(tmp_path: Path) -> None:
    text = _CLAUDE.replace('[harnesses.claude.tiers.deep]\nmodel = "opus"\nefforts = ["medium", "high"]\n', "")

    assert _refusal(tmp_path, text) == "harness claude must define the tiers fast, standard, deep, not fast, standard"


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('model = "haiku"', "", "harness claude tier fast needs a model"),
        (
            'efforts = ["medium", "high"]\n\n[harnesses.claude.tiers.deep]',
            'efforts = "high"\n\n[harnesses.claude.tiers.deep]',
            "harness claude tier standard efforts must be a list of names",
        ),
        ("tiers = [", "tier = [", "tiers must be a non-empty list of names"),
    ],
)
def test_a_malformed_file_is_refused_with_the_harness_and_tier_named(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    assert _refusal(tmp_path, _CLAUDE.replace(old, new, 1)) == message


def test_a_harness_without_a_label_or_sessions_flag_is_named_by_its_key_and_cannot_start_a_session(
    tmp_path: Path,
) -> None:
    text = (
        'tiers = ["fast"]\n[harnesses.codex]\nreason = "no session-start path"\n'
        '[harnesses.codex.tiers.fast]\nmodel = "m"\n'
    )

    codex = _load(tmp_path, text).harnesses["codex"]

    assert (codex.label, codex.sessions, codex.reason) == ("codex", False, "no session-start path")


def test_a_harness_without_a_tiers_table_is_refused_naming_none(tmp_path: Path) -> None:
    text = 'tiers = ["fast"]\n[harnesses.codex]\nsessions = true\n'

    assert _refusal(tmp_path, text) == "harness codex must define the tiers fast, not none"


def test_a_file_with_tiers_and_no_harnesses_loads_empty(tmp_path: Path) -> None:
    config = _load(tmp_path, 'tiers = ["fast", "deep"]\n')

    assert (config.tiers, config.harnesses) == (("fast", "deep"), {})


@pytest.mark.parametrize("tiers", ['[""]', "[1]", '["fast", ""]', '"fast"'])
def test_tier_names_must_be_non_empty_strings_in_a_list(tmp_path: Path, tiers: str) -> None:
    assert _refusal(tmp_path, f"tiers = {tiers}\n") == "tiers must be a non-empty list of names"
