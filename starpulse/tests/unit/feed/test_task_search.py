"""The search index: what a placed task is found by, how an edit or a retraction changes it, and what a query may hold."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event

from starpulse._internal.feed.search import SearchIndex
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


def _found(index: SearchIndex, query: str) -> list[str]:
    return [hit["task"] for hit in index.search(query)]


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


def test_a_database_that_is_not_sqlite_keeps_no_index() -> None:
    engine = create_engine("postgresql+psycopg://u:p@localhost/none")

    assert SearchIndex.open(engine) is None
