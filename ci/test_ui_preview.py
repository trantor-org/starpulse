"""The UI preview's rules: which surfaces a pull request renders, its one comment, and the public demos."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
import ui_preview
import yaml
from starpulse._internal.cli import demo
from ui_preview import (
    DEMO_BRANCH,
    DEMO_REPO,
    ELEMENTS,
    MAIN_FOLDER,
    MARKER,
    MOCKUP,
    PAGES,
    STARPULSE,
    UI_GLOBS,
    DemoLeakError,
    comment_body,
    demo_note,
    failure_body,
    find_comment,
    leaks,
    main,
    pages,
    pr_body_with_demo,
    publish,
    publish_demos,
    publish_failure,
    push_touches_ui,
    rendered_sha,
    scan_demos,
    sub_mockup,
    sub_mockup_name,
    sub_mockups,
    surfaces,
    unpublish_demos,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        (["starpulse/web/src/App.tsx"], [STARPULSE]),
        (["ci/preview.toml"], [STARPULSE]),
        (["ci/ui_preview.py"], [STARPULSE]),
        (["ci/demo_workspace.py"], [STARPULSE]),
        (["ci/workspace/board.yaml"], [STARPULSE]),
        (["ci/slow_tests.py", "ci/test_ui_preview.py", "ci/seeded_server.py"], []),
        ([".github/workflows/ui-preview.yml"], [STARPULSE]),
        (["starpulse/_internal/cli/demo.py"], [STARPULSE]),
        (["design/hub/index.html"], [MOCKUP]),
        (["design/elements/index.html"], [MOCKUP, ELEMENTS]),
        (["starpulse/web/src/style.css"], [STARPULSE, ELEMENTS]),
        (["design/data.js", "starpulse/web/src/features/kanban/Kanban.tsx"], [STARPULSE, MOCKUP]),
        (["starpulse/_internal/server/server.py", "README.md", "starpulse/tests/unit/cli/test_demo.py", ".github/workflows/ci.yml"], []),
    ],
)
def test_surfaces_follow_the_changed_paths(changed: list[str], expected: list[str]) -> None:
    assert surfaces(changed) == expected


@pytest.mark.parametrize(
    ("changed", "code", "printed"),
    [
        (["README.md", "starpulse/web/src/style.css"], 0, f"{STARPULSE}\n{ui_preview.ELEMENTS}\n"),
        (["README.md", "ci/slow_tests.py"], ui_preview.NO_UI, ""),
        ([], ui_preview.NO_UI, ""),
    ],
)
def test_touches_tells_a_runner_whether_a_change_reaches_a_ui_path(
    changed: list[str], code: int, printed: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The Dagu runner gates its build on this exit status, with the paths `git diff --name-only` listed."""
    listing = tmp_path / "changed.txt"
    listing.write_text("".join(f"{path}\n" for path in changed))

    assert main(["--touches", str(listing)]) == code
    assert capsys.readouterr().out == printed


KANBAN = "starpulse/web/src/features/kanban/Kanban.tsx"
DAGS = "starpulse/web/src/features/dags/Dags.tsx"
ORBIT = "starpulse/web/src/features/orbit/orbitDraw.ts"


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        ([KANBAN], ["starpulse-kanban"]),
        ([DAGS], ["starpulse-dags"]),
        ([ORBIT], ["starpulse-orbit"]),
        ([DAGS, KANBAN, "README.md", "design/data.js"], ["starpulse-kanban", "starpulse-dags"]),
        # anything the three view folders do not own may draw on every view
        ([KANBAN, "starpulse/web/src/App.tsx"], list(PAGES[STARPULSE])),
        ([KANBAN, "starpulse/web/src/features/level/ledger.ts"], list(PAGES[STARPULSE])),
        (["starpulse/web/src/features/kanban"], list(PAGES[STARPULSE])),
        (["ci/preview.toml"], list(PAGES[STARPULSE])),
    ],
)
def test_starpulse_shoots_only_the_views_whose_folder_holds_every_changed_page_path(changed: list[str], expected: list[str]) -> None:
    assert list(pages(STARPULSE, changed)) == expected


def test_a_view_keeps_the_query_it_opens_with_and_other_surfaces_keep_every_page() -> None:
    assert pages(STARPULSE, [KANBAN]) == {"starpulse-kanban": "?view=kanban"}
    assert pages(MOCKUP, [KANBAN]) == PAGES[MOCKUP]


SHA = "a" * 40


def preview(sha_line: str, author: str = "bot", comment_id: int = 3) -> dict:
    return {"id": comment_id, "user": {"login": author}, "body": f"{MARKER}\n{sha_line}\n## UI preview"}


def test_the_comment_records_the_commit_it_was_rendered_from() -> None:
    body = comment_body(SHOTS, run_url="u", sha=SHA)
    assert rendered_sha([{"id": 1, "user": {"login": "bot"}, "body": body}], author="bot") == SHA


def test_no_rendered_commit_is_known_without_the_authors_own_comment_naming_one() -> None:
    assert rendered_sha([], author="bot") is None
    assert rendered_sha([preview(f"<!-- rendered: {SHA} -->", author="someone")], author="bot") is None
    assert rendered_sha([preview("## UI preview of `abcdef1`")], author="bot") is None
    assert rendered_sha([preview("<!-- rendered: abcdef1 -->")], author="bot") is None


def compare(*files: str, status: str = "ahead") -> dict:
    return {"status": status, "files": [{"filename": f} for f in files]}


def test_a_push_that_changed_no_ui_path_since_the_last_render_needs_no_render() -> None:
    assert not push_touches_ui(compare("README.md", "starpulse/_internal/server/server.py", "ci/slow_tests.py"))
    assert not push_touches_ui(compare())


def test_a_push_that_changed_a_ui_path_since_the_last_render_renders() -> None:
    assert push_touches_ui(compare("README.md", KANBAN))
    assert push_touches_ui(compare("design/hub/index.html"))


def test_a_file_renamed_out_of_a_ui_path_renders() -> None:
    moved = {"filename": "attic/Kanban.tsx", "previous_filename": KANBAN}
    assert push_touches_ui({"status": "ahead", "files": [moved]})


def test_a_push_the_comparison_cannot_vouch_for_renders() -> None:
    # a rebase or force-push can carry main's UI changes; a failed comparison knows nothing
    assert push_touches_ui(compare("README.md", status="diverged"))
    assert push_touches_ui(compare("README.md", status="behind"))
    assert push_touches_ui(None)
    # GitHub lists at most 300 files, so a full page may hide a UI path
    assert push_touches_ui(compare(*[f"docs/{n}.md" for n in range(300)]))
    assert not push_touches_ui(compare(*[f"docs/{n}.md" for n in range(299)]))


def test_the_workflow_filters_pull_requests_and_main_pushes_on_the_scripts_globs() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ui-preview.yml").read_text())
    # PyYAML reads the `on:` key as True.
    on = workflow[True]
    assert tuple(on["pull_request"]["paths"]) == UI_GLOBS
    assert on["push"] == {"branches": ["main"], "paths": list(UI_GLOBS)}
    assert "workflow_dispatch" in on


def test_the_shipped_mockup_builds_a_demo_that_leaks_nothing() -> None:
    assert leaks(demo.mockup(ROOT / "design")) == []


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        (["design/task-modal/task-modal.js"], ["task-modal"]),
        (["design/hub/index.html", "design/edit/edit.js", "design/hub/hub.js", "starpulse/_internal/server/server.py"], ["edit", "hub"]),
        (["design/index.html", "design/data.js"], []),
        (["design/elements/index.html", "design/elements/elements.js"], []),
        (["starpulse/web/src/features/kanban/Kanban.tsx"], []),
    ],
)
def test_sub_mockups_follow_the_changed_paths(changed: list[str], expected: list[str]) -> None:
    assert sub_mockups(changed) == expected


def test_a_sub_mockup_is_published_under_a_name_the_main_mockup_cannot_take() -> None:
    assert sub_mockup_name("task-modal") == "mockup-task-modal.html"
    assert sub_mockup_name("mockup") != f"{MOCKUP}.html"


def test_a_sub_mockup_inlines_each_local_script_into_its_one_page(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text('<head><script src="layer.js"></script></head><body>page</body>')
    (tmp_path / "layer.js").write_text('el.innerHTML = "</script>";')
    page = sub_mockup(tmp_path)
    assert page == '<head><script>el.innerHTML = "<\\/script>";</script></head><body>page</body>'


def test_the_shipped_layers_mockup_builds_a_demo_that_leaks_nothing() -> None:
    assert leaks(sub_mockup(ROOT / "design" / "layers")) == []


def test_the_shipped_task_modal_mockup_builds_a_demo_that_leaks_nothing() -> None:
    assert leaks(sub_mockup(ROOT / "design" / "task-modal")) == []


def test_the_shipped_element_sheet_builds_a_demo_that_leaks_nothing() -> None:
    assert leaks(demo.elements(ROOT / "design/elements")) == []


SHOTS = {
    STARPULSE: [Path("shots/starpulse-star-map.png"), Path("shots/starpulse-kanban.png")],
    MOCKUP: [Path("shots/design-mockup.png")],
}


def test_comment_opens_with_the_marker_so_a_rerun_finds_it() -> None:
    assert comment_body(SHOTS, run_url="https://x/run/1", sha="abcdef1234567").startswith(MARKER + "\n")


def test_comment_embeds_every_screenshot_under_its_surface() -> None:
    body = comment_body(SHOTS, run_url="https://x/run/1", sha="abcdef1234567")
    flow, mock = body.split(f"### {MOCKUP}")
    assert flow.count("![") == 2
    assert "![starpulse-kanban](./shots/starpulse-kanban.png)" in flow
    assert "![design-mockup](./shots/design-mockup.png)" in mock


def test_comment_names_the_commit_and_run_and_what_each_render_is() -> None:
    body = comment_body(SHOTS, run_url="https://x/run/1", sha="abcdef1234567")
    assert "abcdef1" in body
    assert "https://x/run/1" in body
    assert "ci/preview.toml" in body
    assert "--mockup design" in body


def test_comment_says_how_a_sub_mockup_was_rendered() -> None:
    body = comment_body({"mockup-task-modal": [Path("shots/mockup-task-modal.png")]}, "u", "abcdef1")
    assert "`design/task-modal/`" in body
    assert "![mockup-task-modal](./shots/mockup-task-modal.png)" in body


def test_comment_carries_the_demo_note_under_its_own_heading_only_when_there_is_one() -> None:
    assert "### Demo\nlinks" in comment_body(SHOTS, "u", "abcdef1", demo="links")
    assert "### Demo" not in comment_body(SHOTS, "u", "abcdef1")


def test_find_comment_picks_the_marker_comment_by_the_author() -> None:
    comments = [
        {"id": 1, "user": {"login": "someone"}, "body": f"{MARKER}\nquoted"},
        {"id": 2, "user": {"login": "bot"}, "body": "unrelated"},
        {"id": 3, "user": {"login": "bot"}, "body": f"{MARKER}\nold render"},
    ]
    assert find_comment(comments, author="bot") == 3
    assert find_comment(comments[:2], author="bot") is None


class FakeGh:
    """`gh` as the publish step sees it: a PR's comments, and the calls made against them."""

    def __init__(self, existing: list[dict]) -> None:
        self.comments = {c["id"]: dict(c) for c in existing}  # an edit must not reach the module's shared OLD
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> str:
        self.calls.append(args)
        if args[:2] == ("pr", "comment"):
            self.comments[99] = {
                "id": 99,
                "user": {"login": "bot"},
                "body": f"{MARKER}\nuploaded images",
                "html_url": "https://github.com/o/r/pull/7#issuecomment-99",
            }
            return "https://github.com/o/r/pull/7#issuecomment-99\n"
        if args[0] == "api" and "--paginate" in args:
            return json.dumps([list(self.comments.values())])
        if args[0] == "api" and "--method" not in args:
            return json.dumps(self.comments[int(args[1].rsplit("/", 1)[1])])
        method, route = args[2], args[3]
        comment_id = int(route.rsplit("/", 1)[1])
        if method == "DELETE":
            del self.comments[comment_id]
        else:
            self.comments[comment_id]["body"] = args[5].removeprefix("body=")
        return ""


OLD = {
    "id": 5,
    "user": {"login": "bot"},
    "body": f"{MARKER}\nold",
    "html_url": "https://github.com/o/r/pull/7#issuecomment-5",
}


def publish_to(gh: FakeGh) -> str:
    return publish(gh, repo="o/r", pr=7, body=Path("body.md"), images=[Path("shots/a.png")], author="bot")


def test_first_render_attaches_each_image_and_leaves_one_comment() -> None:
    gh = FakeGh([])
    assert publish_to(gh) == "https://github.com/o/r/pull/7#issuecomment-99"
    assert gh.calls[0] == ("pr", "comment", "7", "--repo", "o/r", "--body-file", "body.md", "--attach", "shots/a.png")
    assert list(gh.comments) == [99]


def test_rerender_edits_the_earlier_comment_in_place_and_drops_the_upload() -> None:
    gh = FakeGh([OLD])
    assert publish_to(gh) == "https://github.com/o/r/pull/7#issuecomment-5"
    assert list(gh.comments) == [5]
    assert gh.comments[5]["body"] == f"{MARKER}\nuploaded images"


def test_rerender_never_touches_a_comment_that_is_not_its_own() -> None:
    gh = FakeGh([{**OLD, "id": 3, "user": {"login": "someone"}}, OLD])
    publish_to(gh)
    assert set(gh.comments) == {3, 5}


def test_note_links_each_demo_in_the_prs_own_folder() -> None:
    note = demo_note(7, ["starpulse.html"])
    assert "(https://trantor-org.github.io/starpulse/pr-7/starpulse.html)" in note
    assert demo_note(7, []) == ""


def test_pr_body_gains_one_demo_section_a_rerun_replaces_and_teardown_removes() -> None:
    once = pr_body_with_demo("Summary.\n", "first")
    twice = pr_body_with_demo(once, "second")
    assert twice.count("<!-- starpulse:ui-demo -->") == 1
    assert "second" in twice and "first" not in twice
    assert pr_body_with_demo(twice, "") == "Summary.\n"


class DemoGh:
    """`gh` as the demo repository sees it: its Pages branch tree, and the writes made against it."""

    def __init__(self, tree: dict[str, str], *, branch: bool = True) -> None:
        self.tree = tree
        self.branch = branch
        self.created: list[str] = []
        self.writes: list[tuple[str, str, dict]] = []

    def __call__(self, *args: str) -> str:
        if args == ("api", f"repos/{DEMO_REPO}/branches/{DEMO_BRANCH}"):
            if not self.branch:
                raise RuntimeError("Not Found")
            return "{}"
        if args == ("api", f"repos/{DEMO_REPO}/git/trees/{DEMO_BRANCH}?recursive=1"):
            return json.dumps({"tree": [{"path": p, "sha": s, "type": "blob"} for p, s in self.tree.items()]})
        method, route = args[2], args[3].removeprefix(f"repos/{DEMO_REPO}/")
        if route.startswith("git/"):
            self.created.append(route)
            self.branch = self.branch or route == "git/refs"
            # GitHub answers a created ref with its target under `object`, and a tree or commit with its own `sha`.
            return json.dumps({"object": {"sha": "created"}} if route == "git/refs" else {"sha": "created"})
        route = route.removeprefix("contents/")
        if method == "PUT":
            self.writes.append((method, route, json.loads(Path(args[5]).read_text())))
        else:
            self.writes.append((method, route, dict(a.split("=", 1) for a in args[5::2])))
        return "{}"


def test_publish_writes_each_demo_and_drops_one_the_pr_no_longer_builds(tmp_path: Path) -> None:
    built = tmp_path / "starpulse.html"
    built.write_text("<html>")
    folder = "pr-7"
    gh = DemoGh({f"{folder}/starpulse.html": "old", f"{folder}/design-mockup.html": "gone", "main/starpulse.html": "m"})

    urls = publish_demos(gh, folder, [built], tmp_path / "scratch")

    assert urls == [f"https://trantor-org.github.io/starpulse/{folder}/starpulse.html"]
    assert gh.writes == [
        (
            "PUT",
            f"{folder}/starpulse.html",
            {
                "message": f"Publish {folder}/starpulse.html",
                "content": base64.b64encode(b"<html>").decode(),
                "branch": DEMO_BRANCH,
                "sha": "old",
            },
        ),
        (
            "DELETE",
            f"{folder}/design-mockup.html",
            {"message": f"Unpublish {folder}/design-mockup.html", "sha": "gone", "branch": DEMO_BRANCH},
        ),
    ]


def test_unpublish_deletes_only_this_prs_folder() -> None:
    gh = DemoGh({"pr-7/a.html": "a", "pr-70/a.html": "b", "main/a.html": "m"})

    unpublish_demos(gh, "pr-7")

    assert gh.writes == [("DELETE", "pr-7/a.html", {"message": "Unpublish pr-7/a.html", "sha": "a", "branch": DEMO_BRANCH})]


def test_publishing_to_a_repository_without_the_pages_branch_creates_it_first(tmp_path: Path) -> None:
    built = tmp_path / "starpulse.html"
    built.write_text("<html>")
    gh = DemoGh({}, branch=False)

    publish_demos(gh, MAIN_FOLDER, [built], tmp_path / "scratch")

    assert gh.created == ["git/trees", "git/commits", "git/refs"]
    assert [(method, route) for method, route, _ in gh.writes] == [("PUT", "main/starpulse.html")]


def test_unpublish_with_no_pages_branch_has_nothing_to_delete() -> None:
    gh = DemoGh({}, branch=False)

    unpublish_demos(gh, "pr-7")

    assert gh.writes == [] and gh.created == []


def test_publishing_main_replaces_mains_demos_and_leaves_every_pr_folder(tmp_path: Path) -> None:
    built = tmp_path / "starpulse.html"
    built.write_text("<html>")
    gh = DemoGh({"main/starpulse.html": "old", "main/gone.html": "g", "pr-7/starpulse.html": "p"})

    urls = publish_demos(gh, MAIN_FOLDER, [built], tmp_path / "scratch")

    assert urls == ["https://trantor-org.github.io/starpulse/main/starpulse.html"]
    assert [(method, route) for method, route, _ in gh.writes] == [
        ("PUT", "main/starpulse.html"),
        ("DELETE", "main/gone.html"),
    ]


def test_publishing_main_carries_its_screenshots_without_leak_scanning_image_bytes(tmp_path: Path) -> None:
    page, shot = tmp_path / "starpulse.html", tmp_path / "starpulse-kanban.png"
    page.write_text("<html>")
    shot.write_bytes(b"\x89PNG TASK-12 /home/x")
    gh = DemoGh({})

    publish_demos(gh, MAIN_FOLDER, [page, shot], tmp_path / "scratch")

    assert [route for _, route, _ in gh.writes] == ["main/starpulse.html", "main/starpulse-kanban.png"]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ('{"title": "fix TASK-2288"}', "task id"),
        (".".join(("192", "168", "0", "154")), "private address"),
        (".".join(("127", "0", "0", "1")), "private address"),
        ('"id": "5a8b9bdd-cdd3-5329-9930-c29448a42085"', "uuid"),
        ("session_0183rN4T2qWXemrmM1Mwem7G", "session id"),
        ("mailto:someone@example.org", "email"),
        ("/" + "home/someone/repo", "home path"),
        ("ghp_" + "a" * 36, "token"),
        ('<a href="https://github.com/o/r/pull/1">', "url"),
    ],
)
def test_each_real_identifier_is_a_leak(text: str, kind: str) -> None:
    assert [hit.split(": ", 1)[0] for hit in leaks(text)] == [kind]


def test_a_scrubbed_demo_carries_no_leak() -> None:
    text = (
        '{"id": "0000002a-0000-4000-8000-000000000000", "task": "DEMO-115"}'
        '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        '<link href="https://fonts.googleapis.com/css2?family=Inter"> "https://react.dev/errors/"'
    )
    assert leaks(text) == []


def test_publish_refuses_every_demo_when_one_leaks(tmp_path: Path) -> None:
    clean, leaky = tmp_path / "starpulse.html", tmp_path / "design-mockup.html"
    clean.write_text("<html>")
    leaky.write_text("<html>TASK-9</html>")
    gh = DemoGh({})

    with pytest.raises(DemoLeakError, match=r"design-mockup\.html: task id: TASK-9"):
        publish_demos(gh, "pr-7", [clean, leaky], tmp_path / "scratch")

    assert gh.writes == []


def test_scan_run_fails_on_a_leaking_demo_and_passes_a_clean_or_absent_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--scan", str(tmp_path / "absent")]) == 0
    (tmp_path / "starpulse.html").write_text("<html>DEMO-1</html>")
    assert main(["--scan", str(tmp_path)]) == 0
    (tmp_path / "design-mockup.html").write_text("<html>TASK-9</html>")
    assert main(["--scan", str(tmp_path)]) == 1
    assert "design-mockup.html: task id: TASK-9" in capsys.readouterr().err


def test_scan_demos_passes_a_clean_demo(tmp_path: Path) -> None:
    clean = tmp_path / "starpulse.html"
    clean.write_text("<html>DEMO-1</html>")
    scan_demos([clean])


def test_a_failed_render_comment_opens_with_the_marker_names_the_run_and_claims_no_render() -> None:
    body = failure_body("https://x/run/1", SHA)
    assert body.startswith(MARKER + "\n")
    assert "failed" in body and "https://x/run/1" in body and SHA[:7] in body
    assert rendered_sha([{"id": 1, "user": {"login": "bot"}, "body": body}], author="bot") is None


def test_a_failed_render_creates_the_comment_when_the_pull_request_has_none() -> None:
    posted: list[tuple[str, ...]] = []

    def gh(*args: str) -> str:
        posted.append(args)
        return "[[]]"

    publish_failure(gh, "o/r", 7, "failed", author="bot")
    assert posted[-1] == ("api", "--method", "POST", "repos/o/r/issues/7/comments", "-f", "body=failed")


def test_a_failed_render_edits_the_earlier_preview_comment_in_place() -> None:
    gh = FakeGh([OLD])
    publish_failure(gh, "o/r", 7, "failed", author="bot")
    assert gh.comments[5]["body"] == "failed"


def test_the_workflow_reports_a_failed_pull_request_render() -> None:
    steps = yaml.safe_load((ROOT / ".github/workflows/ui-preview.yml").read_text())["jobs"]["render"]["steps"]
    step = next(s for s in steps if s.get("name") == "Report a failed render")
    assert "failure()" in step["if"] and "pull_request" in step["if"]
    assert "--failed" in step["run"]


def _fake_run(calls: list[tuple[str, ...]], failures: int, monkeypatch: pytest.MonkeyPatch) -> None:
    left = [failures]

    def run(*cmd: str, env: object = None) -> str:
        calls.append(cmd)
        if cmd[len(_PW) :][0] == "open" and left[0]:
            left[0] -= 1
            raise RuntimeError("Error: Session closed")
        return ""

    monkeypatch.setattr(ui_preview, "_run", run)


_PW = ui_preview._PLAYWRIGHT_CLI + ("-s=x",)


def test_shoot_retries_a_closed_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []
    _fake_run(calls, 1, monkeypatch)
    assert ui_preview._shoot("http://x", tmp_path / "a.png") == tmp_path / "a.png"
    verbs = [c[len(_PW) :][0] for c in calls]
    assert verbs.count("open") == 2
    assert verbs.count("close") == 2


def test_shoot_raises_when_every_try_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []
    _fake_run(calls, 99, monkeypatch)
    with pytest.raises(RuntimeError, match="Session closed"):
        ui_preview._shoot("http://x", tmp_path / "a.png")
    assert [c[len(_PW) :][0] for c in calls].count("open") == 3
