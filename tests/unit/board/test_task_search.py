"""The search index: what a placed task is found by, how an edit or a retraction changes it, and what a query may hold."""

import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from starpulse.board.adapters.search import SearchIndex
from starpulse.contracts.adapters import BoardTask


def _task(task_id: str = "PROJ-1", **fields: object) -> BoardTask:
    return BoardTask.model_validate({"id": task_id, "team": "demo", "title": "t", "lane": "to_do", **fields})


@pytest.fixture
def engine(tmp_path: Path):
    return create_engine(f"sqlite:///{tmp_path / 'search.sqlite'}")


@pytest.fixture
def index(engine) -> SearchIndex:
    opened = SearchIndex.open(engine)
    assert opened is not None
    return opened


def _found(index: SearchIndex, query: str, **filters: object) -> list[str]:
    return [hit["task"] for hit in index.search(query, **filters)]  # type: ignore[arg-type]


def test_a_task_is_found_by_its_title_description_criteria_notes_and_id(index: SearchIndex) -> None:
    index.index(
        _task(
            "PROJ-7",
            title="Rotate the signing keys",
            description="Cycle the certificate authority",
            acceptance_criteria=("Pager stays quiet during rotation",),
            notes="Vault lease renewed twice",
        )
    )

    assert _found(index, "signing") == ["PROJ-7"]
    assert _found(index, "authority") == ["PROJ-7"]
    assert _found(index, "pager") == ["PROJ-7"]
    assert _found(index, "vault") == ["PROJ-7"]
    assert _found(index, "PROJ-7") == ["PROJ-7"]
    assert _found(index, "unrelated") == []


def test_a_hit_names_the_task_its_title_its_lane_and_the_text_that_matched(index: SearchIndex) -> None:
    index.index(_task("PROJ-7", title="Rotate keys", lane="in_progress", description="Cycle the certificate authority"))

    [hit] = index.search("certificate")

    assert hit["task"] == "PROJ-7"
    assert hit["title"] == "Rotate keys"
    assert hit["lane"] == "in_progress"
    assert "certificate" in hit["snippet"]
    assert hit["score"] > 0


def test_a_settled_task_is_found_in_the_lane_it_settled_in(index: SearchIndex) -> None:
    index.index(_task("PROJ-8", title="Retire the cron", settled="archived"))

    assert index.search("cron")[0]["lane"] == "archived"


def test_a_finished_since_bound_drops_the_tasks_that_finished_before_it(index: SearchIndex) -> None:
    index.index(_task("PROJ-1", title="Drain the open queue"))
    index.index(_task("PROJ-2", title="Drain the completed queue", settled="completed", settled_at=100.0))
    index.index(_task("PROJ-3", title="Drain the archived queue", settled="archived", settled_at=100.0))
    index.index(_task("PROJ-4", title="Drain the done queue", lane="done"), finished_at=100.0)
    index.index(_task("PROJ-5", title="Drain the recent queue", settled="completed", settled_at=300.0))

    assert sorted(_found(index, "drain", finished_since=200.0)) == ["PROJ-1", "PROJ-5"]
    assert len(_found(index, "drain")) == 5


def test_a_settled_task_the_board_gives_no_time_for_is_older_than_any_bound(index: SearchIndex) -> None:
    index.index(_task("PROJ-1", title="Drain", settled="completed"))

    assert _found(index, "drain", finished_since=1.0) == []


def test_a_finished_task_placed_again_keeps_the_earlier_of_its_finish_times(engine, index: SearchIndex) -> None:
    index.index(_task("PROJ-1", title="Drain", lane="done"), finished_at=100.0)
    writes: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *args: writes.append(args[2]))

    index.index(_task("PROJ-1", title="Drain", lane="done"), finished_at=300.0)  # a restart dates an undated entry now
    assert [s for s in writes if s.lstrip().upper().startswith(("INSERT", "DELETE", "UPDATE"))] == []
    assert _found(index, "drain", finished_since=200.0) == []

    index.index(_task("PROJ-1", title="Drain", settled="completed", settled_at=50.0))
    assert _found(index, "drain", finished_since=75.0) == []


def test_a_label_filter_keeps_only_the_tasks_carrying_every_named_label(index: SearchIndex) -> None:
    index.index(_task("PROJ-1", title="Drain", labels=["disk", "unraid"]))
    index.index(_task("PROJ-2", title="Drain", labels=["disk"]))
    index.index(_task("PROJ-3", title="Drain", labels=["disk-usage", "unraid"]))

    assert _found(index, "drain", labels=["disk", "unraid"]) == ["PROJ-1"]
    assert sorted(_found(index, "drain", labels=["disk"])) == ["PROJ-1", "PROJ-2"]


def test_a_task_relabelled_or_finished_since_it_was_indexed_is_filtered_by_what_it_is_now(index: SearchIndex) -> None:
    index.index(_task("PROJ-1", title="Drain", labels=["disk"]))

    index.index(_task("PROJ-1", title="Drain", labels=["ci"], settled="completed", settled_at=100.0))

    assert _found(index, "drain", labels=["disk"]) == []
    assert _found(index, "drain", finished_since=200.0) == []
    assert _found(index, "drain", labels=["ci"]) == ["PROJ-1"]


def test_a_title_match_ranks_above_a_description_match(index: SearchIndex) -> None:
    index.index(_task("PROJ-1", title="Unrelated", description="mentions the ledger once"))
    index.index(_task("PROJ-2", title="Ledger rewrite", description="nothing else"))

    assert _found(index, "ledger") == ["PROJ-2", "PROJ-1"]


def test_an_edited_description_is_found_by_its_new_text_and_no_longer_by_its_old(index: SearchIndex) -> None:
    index.index(_task("PROJ-1", description="drain the queue"))

    index.index(_task("PROJ-1", description="rebuild the cache"))

    assert _found(index, "cache") == ["PROJ-1"]
    assert _found(index, "queue") == []


def test_a_task_that_moves_lane_is_found_in_its_new_lane(index: SearchIndex) -> None:
    index.index(_task("PROJ-1", title="Drain", lane="to_do"))

    index.index(_task("PROJ-1", title="Drain", lane="review"))

    assert [hit["lane"] for hit in index.search("drain")] == ["review"]


def test_a_removed_task_is_no_longer_found(index: SearchIndex) -> None:
    index.index(_task("PROJ-1", title="Drain"))

    index.remove("PROJ-1")

    assert _found(index, "drain") == []


def test_placing_a_task_unchanged_writes_nothing(engine, index: SearchIndex) -> None:
    task = _task("PROJ-1", title="Drain", description="the queue")
    index.index(task)
    writes: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, *rest) -> None:
        writes.append(statement)

    index.index(task)
    index.index(_task("PROJ-1", title="Drain", description="the queue"))

    assert [s for s in writes if s.lstrip().upper().startswith(("INSERT", "DELETE", "UPDATE"))] == []


def test_a_reopened_index_keeps_what_it_held_and_skips_what_has_not_changed(engine) -> None:
    first = SearchIndex.open(engine)
    assert first is not None
    task = _task("PROJ-1", title="Drain")
    first.index(task)
    writes: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, *rest) -> None:
        writes.append(statement)

    second = SearchIndex.open(engine)
    assert second is not None
    second.index(task)

    assert [hit["task"] for hit in second.search("drain")] == ["PROJ-1"]
    assert [s for s in writes if s.lstrip().upper().startswith(("INSERT", "DELETE", "UPDATE"))] == []


@pytest.mark.parametrize("query", ["PROJ-45", 'say "hi"', "AND OR NOT", "title:foo", "a*", "(", "NEAR(x y)", "'; DROP"])
def test_a_query_holding_search_syntax_is_a_plain_search_not_an_error(index: SearchIndex, query: str) -> None:
    index.index(_task("PROJ-45", title="the PROJ-45 title"))

    index.search(query)  # raises nothing


def test_a_query_with_several_words_needs_them_all(index: SearchIndex) -> None:
    index.index(_task("PROJ-1", title="Drain the queue"))
    index.index(_task("PROJ-2", title="Drain the cache"))

    assert _found(index, "drain queue") == ["PROJ-1"]


def test_a_blank_query_finds_nothing(index: SearchIndex) -> None:
    index.index(_task("PROJ-1", title="Drain"))

    assert index.search("   ") == []


def test_the_limit_caps_the_hits(index: SearchIndex) -> None:
    for number in range(5):
        index.index(_task(f"PROJ-{number}", title="Drain"))

    assert len(index.search("drain", limit=2)) == 2


def test_a_filtered_search_runs_the_fts_match_before_the_facets_narrowing(engine, index: SearchIndex) -> None:
    """ANDing the facets IN onto MATCH makes SQLite look up each facet rowid in FTS (`0:=M`); MATCH first keeps `0:M`."""
    index.index(_task("PROJ-1", title="Drain", labels=["disk"]))
    statements: list[tuple[str, object]] = []

    def capture(_conn, _cursor, statement, parameters, *_rest) -> None:
        if " MATCH " in statement:
            statements.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        index.search("drain", labels=["disk"], finished_since=0.0)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert statements
    statement, parameters = statements[0]
    with engine.connect() as db:
        plan = " ".join(row[3] for row in db.exec_driver_sql(f"EXPLAIN QUERY PLAN {statement}", parameters))

    assert "0:=M" not in plan
    assert "0:M" in plan


@pytest.fixture(scope="module")
def many(tmp_path_factory: pytest.TempPathFactory):
    """An engine holding 2,500 tasks, half labelled `disk`: seeded once, as the searches timed over it only read it."""
    engine = create_engine(f"sqlite:///{tmp_path_factory.mktemp('many') / 'search.sqlite'}")
    seeding = SearchIndex.open(engine)
    assert seeding is not None
    with engine.begin() as connection:  # one commit, not 2,500: a commit each is what a loaded worker's disk made slow
        for number in range(2500):
            seeding.index_fields(
                f"T-{number}",
                title=f"drain item {number}",
                description="",
                criteria=[],
                notes="",
                lane="to_do",
                labels=["disk"] if number % 2 == 0 else ["other"],
                connection=connection,
            )
    return engine


def test_a_finished_since_filtered_search_of_200_words_returns_in_under_one_second(many) -> None:
    index = SearchIndex.open(many)  # an index of its own, so no search an earlier test ran is held warm
    assert index is not None
    query = "drain " + " ".join(f"unique{n}" for n in range(200))

    started = time.perf_counter()
    index.search(query, finished_since=0.0)
    assert time.perf_counter() - started < 1.0


def test_a_label_filtered_search_of_200_words_returns_in_under_one_second(many) -> None:
    index = SearchIndex.open(many)
    assert index is not None
    query = "drain " + " ".join(f"unique{n}" for n in range(200))

    started = time.perf_counter()
    index.search(query, labels=["disk"])
    assert time.perf_counter() - started < 1.0
