"""The `[level]` config block: the flow graph one level above the Board, its load-time refusals and its facet filter."""

from pathlib import Path

import pytest

from starpulse.domain.level import Activity, Facet, Level, LevelError, Orbit, Terminal
from starpulse.server import assemble
from starpulse.settings.config import ConfigError, load

_LEVEL = """
[level]
machine = "board"
goal = "done"
gates = ["review"]
terminals = [{ id = "done", role = "goal" }, { id = "archived", role = "abandoned" }]
facets = [{ id = "source" }, { id = "type", label = "work type" }]

[level.orbit]
suns = "working"
working = ["in_progress", "review"]

[level.activity]
measure = "flux"
pace = "fast"
"""

_MACHINES = {
    "board": {"states": [{"id": s} for s in ("ready", "in_progress", "review", "done", "archived")]},
    "deploy": {"states": [{"id": "queued"}, {"id": "live"}]},
}


def _load(tmp_path: Path, text: str) -> Level:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    level = load(path).level
    assert level is not None
    return level


def _refusal(tmp_path: Path, text: str) -> str:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    with pytest.raises(ConfigError) as refused:
        load(path)
    return str(refused.value)


def _level(**changes: object) -> Level:
    fields = {
        "machine": "board",
        "goal": "done",
        "gates": ("review",),
        "terminals": (Terminal("done", "goal"), Terminal("archived", "abandoned")),
    }
    return Level(**{**fields, **changes})  # type: ignore[arg-type]


def test_a_config_with_no_level_table_has_no_level(tmp_path: Path) -> None:
    path = tmp_path / "starpulse.toml"
    path.write_text("")

    assert load(path).level is None
    assert load(None).level is None


def test_a_level_table_carries_every_field_the_adr_names(tmp_path: Path) -> None:
    level = _load(tmp_path, _LEVEL)

    assert level == Level(
        machine="board",
        goal="done",
        gates=("review",),
        terminals=(Terminal("done", "goal"), Terminal("archived", "abandoned")),
        orbit=Orbit("working", ("in_progress", "review")),
        facets=(Facet("source", "source"), Facet("type", "work type")),
        activity=Activity("flux", "fast"),
    )


def test_a_level_with_only_its_required_fields_takes_the_documented_defaults(tmp_path: Path) -> None:
    text = '[level]\nmachine = "board"\ngoal = "done"\nterminals = [{ id = "done", role = "goal" }]\n'

    level = _load(tmp_path, text)

    assert (level.gates, level.facets, level.orbit, level.activity) == (
        (),
        (),
        Orbit("terminal", ()),
        Activity("share", "min"),
    )
    assert (level.title, level.subject, level.runs, level.series) == ("Flow graph", "task", "runs", None)


def test_a_level_names_what_the_page_calls_its_subject_runs_title_and_card_series(tmp_path: Path) -> None:
    text = _LEVEL.replace(
        'machine = "board"',
        'machine = "board"\ntitle = "Delivery"\nsubject = "ticket"\nruns = "agent sessions"\nseries = "delivery"',
    )

    level = _load(tmp_path, text)

    assert (level.title, level.subject, level.runs, level.series) == (
        "Delivery",
        "ticket",
        "agent sessions",
        "delivery",
    )


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (('machine = "board"\n', ""), "level needs machine"),
        (('goal = "done"\n', ""), "level needs goal"),
        (
            ('terminals = [{ id = "done", role = "goal" }, { id = "archived", role = "abandoned" }]\n', ""),
            "level needs terminals",
        ),
        (('goal = "done"', 'goal = "archived"\nunknown_field = 1'), "unknown key(s) unknown_field"),
        (
            ('{ id = "archived", role = "abandoned" }', '{ id = "done", role = "abandoned" }'),
            "terminal done is listed twice",
        ),
        (('{ id = "archived", role = "abandoned" }', '{ id = "archived" }'), "terminal archived needs a role"),
        (('goal = "done"', 'goal = "ready"'), "goal ready is not one of the level's terminals"),
        (('suns = "working"', 'suns = "moons"'), "orbit.suns must be terminal or working, not 'moons'"),
        (('working = ["in_progress", "review"]', "working = []"), "orbit.working must name a working state"),
        (('measure = "flux"', 'measure = "mean"'), "activity.measure must be share, count or flux, not 'mean'"),
        (('pace = "fast"', 'pace = "warp"'), "activity.pace must be live, min or fast, not 'warp'"),
        (('{ id = "source" }', '{ id = "source" }, { id = "source" }'), "facet source is listed twice"),
        (('{ id = "source" }', '{ label = "source" }'), "a facet needs an id"),
        (
            ('working = ["in_progress", "review"]', 'working = ["in_progress", "done"]'),
            "orbit.working state done is a terminal",
        ),
    ],
)
def test_a_level_the_schema_cannot_read_is_refused_at_load(tmp_path: Path, edit: tuple[str, str], message: str) -> None:
    assert message in _refusal(tmp_path, _LEVEL.replace(*edit))


def test_a_working_orbit_with_no_working_states_is_refused_even_when_the_key_is_absent(tmp_path: Path) -> None:
    text = _LEVEL.replace('working = ["in_progress", "review"]\n', "")

    assert "orbit.working must name a working state" in _refusal(tmp_path, text)


def test_a_level_whose_states_all_exist_in_its_machine_is_accepted() -> None:
    _level(orbit=Orbit("working", ("in_progress", "review"))).check(_MACHINES)


@pytest.mark.parametrize(
    ("changes", "where", "state"),
    [
        ({"goal": "shipped", "terminals": (Terminal("shipped", "goal"),)}, "goal", "shipped"),
        ({"gates": ("review", "approval")}, "gate", "approval"),
        ({"terminals": (Terminal("done", "goal"), Terminal("cancelled", "abandoned"))}, "terminal", "cancelled"),
        ({"orbit": Orbit("working", ("in_progress", "doing"))}, "orbit.working", "doing"),
    ],
)
def test_a_level_naming_a_state_its_machine_lacks_is_refused_naming_the_state(
    changes: dict[str, object], where: str, state: str
) -> None:
    with pytest.raises(LevelError) as refused:
        _level(**changes).check(_MACHINES)

    assert str(refused.value) == f"level: {where} {state} is not a state of machine board"


def test_a_level_naming_a_machine_the_board_does_not_draw_is_refused() -> None:
    with pytest.raises(LevelError, match="level: machine release is not one the board draws"):
        _level(machine="release").check(_MACHINES)


_RUNS = [
    {"id": "a1", "source": "ana", "facets": {"type": "bug", "repo": "api"}},
    {"id": "a2", "source": "ana", "facets": {"type": "feature", "repo": "api"}},
    {"id": "b1", "source": "bo", "facets": {"type": "bug"}},  # bo's forwarder sends no repo
    {"id": "b2", "source": "bo", "facets": {"type": "feature"}},
]


def _ids(level: Level, select: dict[str, list[str]]) -> list[str]:
    return [run["id"] for run in level.filter(_RUNS, select, lambda run: run["facets"])]


def test_a_facet_filter_keeps_the_runs_whose_value_is_selected() -> None:
    level = _level(facets=(Facet("type", "type"), Facet("repo", "repo")))

    assert _ids(level, {"type": ["bug"]}) == ["a1", "b1"]
    assert _ids(level, {"type": ["bug", "feature"], "repo": ["api"]}) == ["a1", "a2"]


def test_a_facet_filter_excludes_a_run_whose_facet_is_absent_rather_than_counting_it_as_zero() -> None:
    level = _level(facets=(Facet("type", "type"), Facet("repo", "repo")))

    kept = _ids(level, {"repo": ["api"]})

    assert kept == ["a1", "a2"]  # bo's runs carry no repo: they are neither api nor a zero-valued repo
    assert _ids(level, {"repo": ["api", ""]}) == ["a1", "a2"]


def test_no_selection_keeps_every_run_including_one_that_lacks_a_facet() -> None:
    assert _ids(_level(facets=(Facet("repo", "repo"),)), {}) == ["a1", "a2", "b1", "b2"]


def test_a_filter_on_a_facet_the_level_does_not_configure_is_refused() -> None:
    with pytest.raises(LevelError, match="level: facet repo is not configured"):
        _ids(_level(facets=(Facet("type", "type"),)), {"repo": ["api"]})


_NATIVE_LEVEL = '[level]\nmachine = "board"\ngoal = "{goal}"\nterminals = [{{ id = "{goal}", role = "goal" }}]\ngates = ["in_progress"]\n'


def test_serving_a_level_over_a_state_the_board_machine_lacks_is_refused_naming_the_state(tmp_path: Path) -> None:
    path = tmp_path / "starpulse.toml"
    path.write_text(_NATIVE_LEVEL.format(goal="shipped"))

    with pytest.raises(LevelError, match="level: goal shipped is not a state of machine board"):
        assemble(load(path), tmp_path, None, ())


def test_serving_a_level_over_the_states_of_the_board_machine_assembles(tmp_path: Path) -> None:
    path = tmp_path / "starpulse.toml"
    path.write_text(_NATIVE_LEVEL.format(goal="done"))

    assemble(load(path), tmp_path, None, ())
