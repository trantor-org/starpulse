"""The seeded store's cache: a warm run copies the cached `events.sqlite` instead of seeding it, and a change to the recipe
or to any event-log source keys a new entry that seeds again."""

from pathlib import Path

import seeded_server


def _writes_store(seeds: list[Path]):
    def seed(staging: Path) -> None:
        seeds.append(staging)
        (staging / "events.sqlite").write_text("seeded")

    return seed


def test_a_changed_fold_source_changes_the_key(tmp_path: Path) -> None:
    fold = tmp_path / "projector.py"
    fold.write_text("def fold(): return 1\n")
    before = seeded_server.cache_key("recipe", [fold])

    fold.write_text("def fold(): return 2\n")

    assert seeded_server.cache_key("recipe", [fold]) != before


def test_a_changed_recipe_changes_the_key(tmp_path: Path) -> None:
    fold = tmp_path / "projector.py"
    fold.write_text("def fold(): return 1\n")

    assert seeded_server.cache_key("recipe 20000", [fold]) != seeded_server.cache_key("recipe 19999", [fold])


def test_the_key_covers_the_projector_and_the_schema_sources() -> None:
    names = {source.name for source in seeded_server.event_log_sources()}

    assert {"projector.py", "fold.py", "declared.py", "tables.py"} <= names


def test_a_warm_run_copies_the_cached_store_instead_of_seeding(tmp_path: Path) -> None:
    seeds: list[Path] = []
    seed = _writes_store(seeds)

    cold = seeded_server.seeded_database(tmp_path / "cold", "key", seed, root=tmp_path / "cache")
    warm = seeded_server.seeded_database(tmp_path / "warm", "key", seed, root=tmp_path / "cache")

    assert len(seeds) == 1
    assert cold.read_text() == warm.read_text() == "seeded"


def test_a_new_key_seeds_again(tmp_path: Path) -> None:
    seeds: list[Path] = []
    seed = _writes_store(seeds)

    seeded_server.seeded_database(tmp_path / "old", "old-key", seed, root=tmp_path / "cache")
    seeded_server.seeded_database(tmp_path / "new", "new-key", seed, root=tmp_path / "cache")

    assert len(seeds) == 2
