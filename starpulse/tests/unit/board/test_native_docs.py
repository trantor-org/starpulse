"""Doc records on the native board: Backlog.md's `docs/**/doc-N - slug.md` files, read, created, updated, archived and restored."""

import json
import shutil
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from starpulse._internal.board import native, native_docs
from starpulse._internal.board.seam import Board
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse._internal.server.writes import create_doc
from starpulse._internal.cli import agent_cli as cli
from starpulse.contracts.api import RESPONSES
from starpulse._internal.feed.board_feed import BoardFeed

FIXTURE = Path(__file__).resolve().parent.parent.parent / "fixtures" / "native_board" / "docs"
REAL = "specs/doc-84 - Nightly-infrastructure-audit-—-2026-10-04.md"
BODY = "Unattended nightly-audit run for 2026-10-04. The run replaces this with its report.\n"


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native_docs, "_stamp", lambda: "2026-10-08 09:30")


@pytest.fixture
def served(tmp_path: Path) -> tuple[Board, Path]:
    """A native board whose `docs/` holds a copy of a real Backlog.md doc file under `specs/`."""
    built = native.board({}, tmp_path)
    docs = tmp_path / ".starpulse" / "board" / "docs"
    shutil.copytree(FIXTURE, docs)
    return built, docs


def _names(docs: Path) -> list[str]:
    return sorted(str(path.relative_to(docs)) for path in docs.rglob("*") if path.is_file())


def test_native_doc_list_reads_a_real_backlog_file_unchanged_and_without_its_body(served: tuple[Board, Path]) -> None:
    built, docs = served
    before = (docs / REAL).read_bytes()

    assert built.docs is not None
    [record] = built.docs()

    assert record == {
        "id": "doc-84",
        "title": "Nightly infrastructure audit — 2026-10-04",
        "type": "specification",
        "created_date": "2026-10-04 09:00",
        "updated_date": "2026-10-04 09:00",
        "path": REAL,
    }
    assert (docs / REAL).read_bytes() == before


def test_native_doc_list_is_by_ascending_number_across_folders_and_skips_the_archive(
    served: tuple[Board, Path],
) -> None:
    built, docs = served
    (docs / "doc-9 - nine.md").write_text("---\nid: doc-9\ntitle: Nine\ntype: other\n---\nnine\n")
    (docs.parent / "archive" / "docs").mkdir(parents=True)
    (docs.parent / "archive" / "docs" / "doc-1 - old.md").write_text("---\nid: doc-1\ntitle: Old\n---\n")
    (docs / "evidence").mkdir()
    (docs / "evidence" / "ledger.png").write_bytes(b"\x89PNG")

    assert built.docs is not None
    assert [record["id"] for record in built.docs()] == ["doc-9", "doc-84"]


def test_native_doc_read_answers_one_record_with_its_body_or_none(served: tuple[Board, Path]) -> None:
    built, _ = served

    assert built.read_doc is not None
    record = built.read_doc("doc-84")
    assert (record["type"], record["body"], record["path"]) == ("specification", BODY, REAL)
    assert built.read_doc("doc-9") is None


def test_native_doc_create_writes_a_backlog_file_under_a_folder_with_the_next_id_past_the_archive(
    served: tuple[Board, Path],
) -> None:
    built, docs = served
    archived = docs.parent / "archive" / "docs"
    archived.mkdir(parents=True)
    (archived / "doc-200 - old.md").write_text("---\nid: doc-200\ntitle: Old\n---\n")

    assert built.create_doc is not None
    written = built.create_doc(
        'Draw: the "board", it\'s fast / slow',
        {"type": "specification", "folder": "specs", "body": "# Plan\n\nDo it.\n"},
    )

    assert (written.ok, written.output) == (True, "doc-201")
    assert (docs / "specs" / "doc-201 - Draw-the-board-its-fast-slow.md").read_text() == (
        "---\nid: doc-201\ntitle: 'Draw: the \"board\", it''s fast / slow'\ntype: specification\n"
        "created_date: '2026-10-08 09:30'\nupdated_date: '2026-10-08 09:30'\n---\n# Plan\n\nDo it.\n"
    )
    assert built.read_doc is not None
    assert built.read_doc("doc-201")["body"] == "# Plan\n\nDo it.\n"


def test_native_doc_create_defaults_to_type_other_at_the_top_of_docs(served: tuple[Board, Path]) -> None:
    built, docs = served

    assert built.create_doc is not None
    assert built.create_doc("Notes", {}).output == "doc-85"

    assert (docs / "doc-85 - Notes.md").read_text().startswith("---\nid: doc-85\ntitle: Notes\ntype: other\n")


@pytest.mark.parametrize(
    ("title", "details"),
    [
        ("  ", {}),
        ("x", {"type": "memo"}),
        ("x", {"folder": "../escape"}),
        ("x", {"folder": "/abs"}),
        ("x", {"owner": "me"}),
        ("x", {"body": 3}),
    ],
)
def test_native_doc_create_refuses_what_it_cannot_file_and_writes_nothing(
    served: tuple[Board, Path], title: str, details: dict
) -> None:
    built, docs = served
    before = _names(docs)

    assert built.create_doc is not None
    assert not built.create_doc(title, details).ok

    assert _names(docs) == before
    assert not (docs.parent / "escape").exists()


def test_native_doc_update_of_the_body_keeps_every_other_line_and_stamps_updated_date(
    served: tuple[Board, Path],
) -> None:
    built, docs = served
    before = (docs / REAL).read_text()

    assert built.edit_doc is not None
    assert built.edit_doc("doc-84", {"body": "Report.\n"}).ok

    assert (docs / REAL).read_text() == before.replace(BODY, "Report.\n").replace(
        "updated_date: '2026-10-04 09:00'", "updated_date: '2026-10-08 09:30'"
    )


def test_native_doc_update_that_changes_nothing_leaves_the_real_file_identical(served: tuple[Board, Path]) -> None:
    built, docs = served
    before = (docs / REAL).read_bytes()

    assert built.edit_doc is not None
    assert built.edit_doc("doc-84", {"body": BODY, "type": "specification"}).ok

    assert (docs / REAL).read_bytes() == before


def test_native_doc_update_of_the_title_renames_the_file_in_its_folder_and_keeps_the_id(
    served: tuple[Board, Path],
) -> None:
    built, docs = served

    assert built.edit_doc is not None
    assert built.edit_doc("doc-84", {"title": "Audit: nightly", "type": "other"}).ok

    assert _names(docs) == ["specs/doc-84 - Audit-nightly.md"]
    assert built.read_doc is not None
    record = built.read_doc("doc-84")
    assert (record["title"], record["type"], record["body"]) == ("Audit: nightly", "other", BODY)
    assert record["created_date"] == "2026-10-04 09:00"


@pytest.mark.parametrize(
    ("doc", "changes"),
    [
        ("doc-9", {"body": "x"}),
        ("doc-84", {"owner": "x"}),
        ("doc-84", {"body": 3}),
        ("doc-84", {"type": "memo"}),
        ("doc-84", {"title": " "}),
    ],
)
def test_native_doc_update_refuses_what_it_cannot_apply_and_writes_nothing(
    served: tuple[Board, Path], doc: str, changes: dict
) -> None:
    built, docs = served
    before = (docs / REAL).read_bytes()

    assert built.edit_doc is not None
    assert not built.edit_doc(doc, changes).ok

    assert _names(docs) == [REAL]
    assert (docs / REAL).read_bytes() == before


def test_native_doc_archive_moves_the_file_under_archive_docs_and_off_the_list(served: tuple[Board, Path]) -> None:
    built, docs = served

    assert built.archive_doc is not None
    assert built.archive_doc("doc-84").ok

    assert _names(docs) == []
    assert (docs.parent / "archive" / "docs" / Path(REAL).name).is_file()
    assert built.docs is not None
    assert built.docs() == []
    assert not built.archive_doc("doc-84").ok
    assert built.create_doc is not None
    assert built.create_doc("Next", {}).output == "doc-85"


ARCHIVED = "doc-84 - Nightly-infrastructure-audit-—-2026-10-04.md"


@pytest.mark.parametrize(
    ("args", "folder"),
    [(("doc-84",), ""), (("doc-84", ""), ""), (("doc-84", "specs"), "specs"), (("doc-84", "guides/old"), "guides/old")],
    ids=["default", "blank", "specs", "nested"],
)
def test_native_doc_restore_returns_the_archived_file_unchanged_under_the_folder_named(
    served: tuple[Board, Path], args: tuple[str, ...], folder: str
) -> None:
    built, docs = served
    before = (docs / REAL).read_bytes()
    assert built.archive_doc is not None
    assert built.restore_doc is not None
    assert built.archive_doc("doc-84").ok

    assert built.restore_doc(*args).ok

    assert (docs / folder / ARCHIVED).read_bytes() == before
    assert not (docs.parent / "archive" / "docs" / ARCHIVED).exists()
    assert built.read_doc is not None
    record = built.read_doc("doc-84")
    assert record is not None
    assert record["path"] == (Path(folder) / ARCHIVED).as_posix()


@pytest.mark.parametrize(
    ("put", "folder"),
    [
        (f"specs/{ARCHIVED}", "specs"),  # the destination file exists
        (f"guides/{ARCHIVED}", "specs"),  # the id is open in another folder
        (None, "../outside"),
        (None, "/etc"),
        (None, "a//b"),
    ],
    ids=["destination-exists", "id-open-elsewhere", "leaves-docs", "absolute", "empty-segment"],
)
def test_native_doc_restore_is_refused_and_writes_nothing(served: tuple[Board, Path], put: str | None, folder: str) -> None:
    built, docs = served
    assert built.archive_doc is not None
    assert built.restore_doc is not None
    archived = docs.parent / "archive" / "docs" / ARCHIVED
    assert built.archive_doc("doc-84").ok
    held = archived.read_bytes()
    if put is not None:
        (docs / put).parent.mkdir(parents=True, exist_ok=True)
        (docs / put).write_bytes(b"---\nid: doc-84\ntitle: Open\n---\n" if put.startswith("guides") else b"active\n")

    assert not built.restore_doc("doc-84", folder).ok

    assert archived.read_bytes() == held
    assert _names(docs) == ([put] if put else [])


def test_native_doc_restore_of_a_doc_that_is_not_archived_is_refused(served: tuple[Board, Path]) -> None:
    built, docs = served
    assert built.restore_doc is not None

    assert not built.restore_doc("doc-9").ok
    assert not built.restore_doc("doc-84", "specs").ok  # open, not archived

    assert _names(docs) == [REAL]


def _call(server: ThreadingHTTPServer, route: str, body: dict | None = None) -> tuple[int, Any]:
    request = urllib.request.Request(
        url(server, route),
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as refusal:
        return refusal.code, json.load(refusal)


def test_native_doc_routes_list_show_create_update_and_archive_over_http(
    served: tuple[Board, Path], tmp_path: Path
) -> None:
    built, docs = served
    with serve(tmp_path, BoardFeed(), milestones=built) as server:
        listed = _call(server, "/api/docs")
        shown = _call(server, "/api/docs/doc-84")
        missing = _call(server, "/api/docs/doc-9")
        created = _call(server, "/api/docs", {"title": "Next", "type": "guide", "body": "Hi\n"})
        updated = _call(server, "/api/docs/edit", {"doc": "doc-85", "changes": {"body": "Bye\n"}})
        unchanged = _call(server, "/api/docs/edit", {"doc": "doc-85", "changes": {"body": "Bye\n"}})
        archived = _call(server, "/api/docs/archive", {"doc": "doc-85"})
        refused = _call(server, "/api/docs/archive", {"doc": "doc-85"})

    TypeAdapter(RESPONSES["/api/docs"]).validate_python(listed[1])
    TypeAdapter(RESPONSES["/api/docs/"]).validate_python(shown[1])
    assert [record["id"] for record in listed[1]["docs"]] == ["doc-84"]
    assert "body" not in listed[1]["docs"][0]
    assert (shown[0], shown[1]["doc"]["body"]) == (200, BODY)
    assert missing[0] == 404
    assert (created, updated, unchanged, archived) == (
        (201, {"doc": "doc-85"}),
        (200, {"doc": "doc-85", "changed": ["body"]}),
        (200, {"doc": "doc-85", "changed": []}),
        (200, {"doc": "doc-85"}),
    )
    assert refused[0] == 404
    assert (docs.parent / "archive" / "docs" / "doc-85 - Next.md").is_file()


def test_native_doc_restore_route_answers_the_doc_and_the_writers_refusal(
    served: tuple[Board, Path], tmp_path: Path
) -> None:
    built, docs = served
    with serve(tmp_path, BoardFeed(), milestones=built) as server:
        archived = _call(server, "/api/docs/archive", {"doc": "doc-84"})
        restored = _call(server, "/api/docs/restore", {"doc": "doc-84", "folder": "specs"})
        again = _call(server, "/api/docs/restore", {"doc": "doc-84", "folder": "specs"})
        no_doc = _call(server, "/api/docs/restore", {"folder": "specs"})
        bad_folder = _call(server, "/api/docs/restore", {"doc": "doc-84", "folder": 3})
        with pytest.raises(urllib.error.HTTPError) as read:
            urllib.request.urlopen(url(server, "/api/docs/restore"), timeout=5)

    assert (archived[0], restored) == (200, (200, {"doc": "doc-84"}))
    assert again[0] == 409
    assert "doc-84" in again[1]["error"]
    assert (no_doc[0], bad_folder[0], read.value.code) == (400, 400, 405)
    assert (docs / "specs" / ARCHIVED).is_file()


@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("/api/docs", {"title": "x"}),
        ("/api/docs/edit", {"doc": "doc-1", "changes": {"title": "y"}}),
        ("/api/docs/restore", {"doc": "doc-1"}),
    ],
)
def test_native_doc_routes_on_a_board_without_docs_are_404(tmp_path: Path, route: str, body: dict) -> None:
    with serve(tmp_path, BoardFeed()) as server:
        assert _call(server, route, body)[0] == 404
        assert _call(server, "/api/docs")[0] == 404


@pytest.mark.parametrize(
    "raw", [b"not json", b"{}", b'{"title": 3}', b'{"title": "x", "body": 3}', b'{"title": "x", "owner": "me"}']
)
def test_native_doc_create_with_a_bad_body_is_a_400_and_writes_nothing(served: tuple[Board, Path], raw: bytes) -> None:
    built, docs = served

    status, _ = create_doc("127.0.0.1", raw, built)

    assert status == 400
    assert _names(docs) == [REAL]


def test_native_doc_create_from_outside_the_lan_is_refused_and_writes_nothing(served: tuple[Board, Path]) -> None:
    built, docs = served

    status, _ = create_doc("8.8.8.8", b'{"title": "x"}', built)

    assert status == 403
    assert _names(docs) == [REAL]


def _verb(capsys: pytest.CaptureFixture[str], server: ThreadingHTTPServer, *argv: str) -> tuple[int, Any]:
    code = cli.main([*argv, "--server", f"http://127.0.0.1:{server.server_port}"], {})
    out = capsys.readouterr()
    assert out.err == ""
    return code, json.loads(out.out)


def test_native_doc_cli_show_json_returns_the_doc_type_and_body(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built = native.board({}, tmp_path)
    folder = tmp_path / ".starpulse" / "board" / "docs" / "specs"
    folder.mkdir(parents=True)
    (folder / "doc-1 - Plan.md").write_text(
        "---\nid: doc-1\ntitle: Plan\ntype: specification\ncreated_date: '2026-10-01 08:00'\n"
        "updated_date: '2026-10-01 08:00'\n---\n# Plan\n\nBody text.\n"
    )
    with serve(tmp_path, BoardFeed(), milestones=built) as server:
        code, doc = _verb(capsys, server, "doc", "show", "doc-1", "--json")

    assert code == 0
    assert (doc["id"], doc["type"], doc["body"]) == ("doc-1", "specification", "# Plan\n\nBody text.\n")


def test_native_doc_cli_lists_creates_updates_and_archives(
    served: tuple[Board, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built, docs = served
    with serve(tmp_path, BoardFeed(), milestones=built) as server:
        listed = _verb(capsys, server, "doc", "list", "--json")
        created = _verb(
            capsys, server, "doc", "create", "Next", "--type", "guide", "--folder", "guides", "--body", "Hi\n"
        )
        shown = _verb(capsys, server, "doc", "show", "doc-85")
        updated = _verb(capsys, server, "doc", "update", "doc-85", "--title", "Later", "--body", "Bye\n")
        archived = _verb(capsys, server, "doc", "archive", "doc-85")
        gone = _verb(capsys, server, "doc", "show", "doc-85")

    assert [record["id"] for record in listed[1]["docs"]] == ["doc-84"]
    assert created == (0, {"doc": "doc-85"})
    assert (shown[1]["type"], shown[1]["path"]) == ("guide", "guides/doc-85 - Next.md")
    assert updated == (0, {"doc": "doc-85", "changed": ["title", "body"]})
    assert archived == (0, {"doc": "doc-85"})
    assert (gone[0], gone[1]["code"]) == (4, "not_found")
    assert (docs.parent / "archive" / "docs" / "doc-85 - Later.md").is_file()


def test_native_doc_cli_restores_an_archived_doc_into_the_folder_named(
    served: tuple[Board, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built, docs = served
    with serve(tmp_path, BoardFeed(), milestones=built) as server:
        archived = _verb(capsys, server, "doc", "archive", "doc-84")
        restored = _verb(capsys, server, "doc", "restore", "doc-84", "--folder", "specs")
        again = _verb(capsys, server, "doc", "restore", "doc-84")

    assert (archived, restored) == ((0, {"doc": "doc-84"}), (0, {"doc": "doc-84"}))
    assert (again[0], again[1]["code"]) == (1, "refused")
    assert (docs / "specs" / ARCHIVED).is_file()


def test_native_doc_cli_update_with_nothing_to_change_is_a_usage_error(
    served: tuple[Board, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built, _ = served
    with serve(tmp_path, BoardFeed(), milestones=built) as server:
        code, doc = _verb(capsys, server, "doc", "update", "doc-84")

    assert (code, doc["code"]) == (2, "usage")
