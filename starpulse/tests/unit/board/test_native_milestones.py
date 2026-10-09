"""Milestone records on the native board: Backlog.md's `milestones/m-N - slug.md` files, read, added, edited and archived."""

import json
import shutil
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from starpulse._internal.board import native
from starpulse._internal.board.seam import Board
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse._internal.server.writes import create_milestone
from starpulse._internal.cli import agent_cli as cli
from starpulse.contracts.api import RESPONSES
from starpulse._internal.feed.board_feed import BoardFeed

FIXTURE = Path(__file__).resolve().parent.parent.parent / "fixtures" / "native_board" / "milestones"
REAL = "m-106 - starpulse-gitlink-promotes-one-green-sha.md"
OUTCOME = (
    "A starpulse merge reaches trantor main within 30 min of its CI going green, through a bump PR that is never "
    "force-pushed and whose Validate is never cancelled; Renovate no longer manages starpulse"
)


@pytest.fixture
def served(tmp_path: Path) -> tuple[Board, Path]:
    """A native board whose `milestones/` holds a copy of a real Backlog.md milestone file."""
    built = native.board({}, tmp_path)
    milestones = tmp_path / ".starpulse" / "board" / "milestones"
    milestones.mkdir()
    shutil.copy(FIXTURE / REAL, milestones / REAL)
    return built, milestones


def test_native_milestone_list_reads_a_real_backlog_file_unchanged(served: tuple[Board, Path]) -> None:
    built, milestones = served
    before = (milestones / REAL).read_bytes()

    assert built.milestones is not None
    [record] = built.milestones()

    assert record["id"] == "m-106"
    assert record["title"] == "StarPulse gitlink promotes one green SHA"
    assert record["outcome"] == OUTCOME
    assert record["specs"] == [
        "doc-108 — backlog/docs/specs/doc-108 - StarPulse-gitlink-moves-by-promoting-one-green-SHA-per-pull-request.md"
    ]
    assert record["adrs"] == ["docs/adr/the-starpulse-gitlink-moves-by-promoting-one-green-sha.md"]
    assert record["retro"].startswith("Opens when the first task")
    assert (milestones / REAL).read_bytes() == before


def test_native_milestone_read_answers_one_record_or_none(served: tuple[Board, Path]) -> None:
    built, _ = served

    assert built.read_milestone is not None
    assert built.read_milestone("m-106")["title"] == "StarPulse gitlink promotes one green SHA"
    assert built.read_milestone("m-9") is None


def test_native_milestone_add_writes_a_backlog_file_with_the_next_id_past_the_archive(
    served: tuple[Board, Path],
) -> None:
    built, milestones = served
    archived = milestones.parent / "archive" / "milestones"
    archived.mkdir(parents=True)
    (archived / "m-200 - old.md").write_text('---\nid: m-200\ntitle: "Old"\n---\n\n## Description\n\n')

    assert built.create_milestone is not None
    written = built.create_milestone(
        'Draw the "board": fast, 1/2',
        {
            "outcome": "It draws",
            "specs": ["doc-1 — a.md"],
            "adrs": ["docs/adr/a.md", "docs/adr/b.md"],
            "retro": "Later.",
        },
    )

    assert (written.ok, written.output) == (True, "m-201")
    assert (milestones / "m-201 - draw-the-board-fast,-12.md").read_text() == (
        '---\nid: m-201\ntitle: "Draw the \\"board\\": fast, 1/2"\n---\n\n## Description\n\n'
        "## Outcome\n\nIt draws\n\n## Spec\n\n- doc-1 — a.md\n\n## ADRs\n\n- docs/adr/a.md\n- docs/adr/b.md\n\n## Retro\n\nLater.\n"
    )
    assert built.read_milestone is not None
    assert built.read_milestone("m-201")["specs"] == ["doc-1 — a.md"]


def test_native_milestone_add_refuses_a_blank_title_and_writes_nothing(served: tuple[Board, Path]) -> None:
    built, milestones = served

    assert built.create_milestone is not None
    written = built.create_milestone("  ", {})

    assert not written.ok
    assert [path.name for path in milestones.iterdir()] == [REAL]


def test_native_milestone_edit_replaces_only_the_given_sections_and_keeps_the_rest_byte_for_byte(
    served: tuple[Board, Path],
) -> None:
    built, milestones = served
    path = milestones / REAL
    path.write_text(path.read_text().replace("## Retro", "## Notes\n\nkept\n\n## Retro"))
    before = path.read_text()

    assert built.edit_milestone is not None
    written = built.edit_milestone("m-106", {"outcome": "Ships in 10 min", "adrs": ["docs/adr/x.md", "docs/adr/y.md"]})

    assert written.ok
    after = path.read_text()
    assert after == before.replace(OUTCOME, "Ships in 10 min").replace(
        "- docs/adr/the-starpulse-gitlink-moves-by-promoting-one-green-sha.md", "- docs/adr/x.md\n- docs/adr/y.md"
    )
    assert "## Notes\n\nkept\n" in after


def test_native_milestone_edit_that_changes_nothing_leaves_the_real_file_identical(served: tuple[Board, Path]) -> None:
    built, milestones = served
    before = (milestones / REAL).read_bytes()

    assert built.edit_milestone is not None
    written = built.edit_milestone("m-106", {"outcome": OUTCOME, "title": "StarPulse gitlink promotes one green SHA"})

    assert written.ok
    assert (milestones / REAL).read_bytes() == before


def test_native_milestone_edit_of_the_title_renames_the_file_and_keeps_the_id(served: tuple[Board, Path]) -> None:
    built, milestones = served

    assert built.edit_milestone is not None
    assert built.edit_milestone("m-106", {"title": "Promote one SHA"}).ok

    assert [path.name for path in milestones.iterdir()] == ["m-106 - promote-one-sha.md"]
    assert built.read_milestone is not None
    assert built.read_milestone("m-106")["title"] == "Promote one SHA"


@pytest.mark.parametrize(
    ("milestone", "changes"),
    [("m-9", {"outcome": "x"}), ("m-106", {"owner": "x"}), ("m-106", {"specs": "doc-1"}), ("m-106", {"title": " "})],
)
def test_native_milestone_edit_refuses_what_it_cannot_apply_and_writes_nothing(
    served: tuple[Board, Path], milestone: str, changes: dict
) -> None:
    built, milestones = served
    before = (milestones / REAL).read_bytes()

    assert built.edit_milestone is not None
    assert not built.edit_milestone(milestone, changes).ok

    assert [path.name for path in milestones.iterdir()] == [REAL]
    assert (milestones / REAL).read_bytes() == before


def test_native_milestone_archive_moves_the_file_under_archive_and_off_the_list(served: tuple[Board, Path]) -> None:
    built, milestones = served

    assert built.archive_milestone is not None
    assert built.archive_milestone("m-106").ok

    assert not (milestones / REAL).exists()
    assert (milestones.parent / "archive" / "milestones" / REAL).is_file()
    assert built.milestones is not None
    assert built.milestones() == []
    assert not built.archive_milestone("m-106").ok


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


def test_native_milestone_routes_list_show_add_edit_and_archive_over_http(
    served: tuple[Board, Path], tmp_path: Path
) -> None:
    built, milestones = served
    with serve(tmp_path, BoardFeed(), milestones=built) as server:
        listed = _call(server, "/api/milestones")
        shown = _call(server, "/api/milestones/m-106")
        missing = _call(server, "/api/milestones/m-9")
        added = _call(server, "/api/milestones", {"title": "Next", "outcome": "Done", "specs": ["doc-1 — a.md"]})
        edited = _call(server, "/api/milestones/edit", {"milestone": "m-107", "changes": {"outcome": "Done well"}})
        unchanged = _call(server, "/api/milestones/edit", {"milestone": "m-107", "changes": {"outcome": "Done well"}})
        archived = _call(server, "/api/milestones/archive", {"milestone": "m-107"})
        refused = _call(server, "/api/milestones/archive", {"milestone": "m-107"})

    TypeAdapter(RESPONSES["/api/milestones"]).validate_python(listed[1])
    assert [record["id"] for record in listed[1]["milestones"]] == ["m-106"]
    assert (shown[0], shown[1]["milestone"]["outcome"]) == (200, OUTCOME)
    assert missing[0] == 404
    assert (added, edited, unchanged, archived) == (
        (201, {"milestone": "m-107"}),
        (200, {"milestone": "m-107", "changed": ["outcome"]}),
        (200, {"milestone": "m-107", "changed": []}),
        (200, {"milestone": "m-107"}),
    )
    assert refused[0] == 404
    assert (milestones.parent / "archive" / "milestones" / "m-107 - next.md").is_file()


@pytest.mark.parametrize(
    ("route", "body"),
    [("/api/milestones", {"title": "x"}), ("/api/milestones/edit", {"milestone": "m-1", "changes": {"title": "y"}})],
)
def test_native_milestone_routes_on_a_board_without_milestones_are_404(tmp_path: Path, route: str, body: dict) -> None:
    with serve(tmp_path, BoardFeed()) as server:
        assert _call(server, route, body)[0] == 404
        assert _call(server, "/api/milestones")[0] == 404


@pytest.mark.parametrize(
    "raw", [b"not json", b"{}", b'{"title": 3}', b'{"title": "x", "specs": "doc-1"}', b'{"title": "x", "owner": "me"}']
)
def test_native_milestone_add_with_a_bad_body_is_a_400_and_writes_nothing(
    served: tuple[Board, Path], raw: bytes
) -> None:
    built, milestones = served

    status, _ = create_milestone("127.0.0.1", raw, built)

    assert status == 400
    assert [path.name for path in milestones.iterdir()] == [REAL]


def test_native_milestone_add_from_outside_the_lan_is_refused_and_writes_nothing(served: tuple[Board, Path]) -> None:
    built, milestones = served

    status, _ = create_milestone("8.8.8.8", b'{"title": "x"}', built)

    assert status == 403
    assert [path.name for path in milestones.iterdir()] == [REAL]


def _verb(capsys: pytest.CaptureFixture[str], server: ThreadingHTTPServer, *argv: str) -> tuple[int, Any]:
    code = cli.main([*argv, "--server", f"http://127.0.0.1:{server.server_port}"], {})
    out = capsys.readouterr()
    assert out.err == ""
    return code, json.loads(out.out)


def test_native_milestone_cli_list_json_lists_the_real_file_with_title_outcome_specs_and_adrs(
    served: tuple[Board, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built, _ = served
    with serve(tmp_path, BoardFeed(), milestones=built) as server:
        code, doc = _verb(capsys, server, "milestone", "list", "--json")

    assert code == 0
    [record] = doc["milestones"]
    assert (record["id"], record["title"], record["outcome"]) == (
        "m-106",
        "StarPulse gitlink promotes one green SHA",
        OUTCOME,
    )
    assert record["specs"] == built.read_milestone("m-106")["specs"] and len(record["specs"]) == 1
    assert record["adrs"] == ["docs/adr/the-starpulse-gitlink-moves-by-promoting-one-green-sha.md"]


def test_native_milestone_cli_adds_shows_edits_and_archives(
    served: tuple[Board, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built, milestones = served
    with serve(tmp_path, BoardFeed(), milestones=built) as server:
        added = _verb(
            capsys,
            server,
            "milestone",
            "add",
            "Next",
            "--outcome",
            "Done",
            "--spec",
            "doc-1 — a.md",
            "--spec",
            "doc-2 — b.md",
            "--adr",
            "docs/adr/a.md",
        )
        shown = _verb(capsys, server, "milestone", "show", "m-107")
        edited = _verb(capsys, server, "milestone", "edit", "m-107", "--title", "Later", "--spec", "doc-3 — c.md")
        archived = _verb(capsys, server, "milestone", "archive", "m-107")
        gone = _verb(capsys, server, "milestone", "show", "m-107")

    assert added == (0, {"milestone": "m-107"})
    assert shown[0] == 0 and (shown[1]["specs"], shown[1]["adrs"]) == (
        ["doc-1 — a.md", "doc-2 — b.md"],
        ["docs/adr/a.md"],
    )
    assert edited == (0, {"milestone": "m-107", "changed": ["title", "specs"]})
    assert archived == (0, {"milestone": "m-107"})
    assert (gone[0], gone[1]["code"]) == (4, "not_found")
    assert (milestones.parent / "archive" / "milestones" / "m-107 - later.md").is_file()


def test_native_milestone_cli_edit_with_nothing_to_change_is_a_usage_error(
    served: tuple[Board, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built, _ = served
    with serve(tmp_path, BoardFeed(), milestones=built) as server:
        code, doc = _verb(capsys, server, "milestone", "edit", "m-106")

    assert (code, doc["code"]) == (2, "usage")
