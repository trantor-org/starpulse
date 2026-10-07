"""The UI preview's rules: which surfaces a pull request renders, its one comment, and the public demos."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
import yaml
from ui_preview import (
    DEMO_REPO,
    ELEMENTS,
    FLOW_VIEW,
    MAIN_FOLDER,
    MARKER,
    MOCKUP,
    UI_GLOBS,
    DemoLeakError,
    comment_body,
    demo_note,
    find_comment,
    leaks,
    main,
    pr_body_with_demo,
    publish,
    publish_demos,
    scan_demos,
    sub_mockup,
    sub_mockup_name,
    sub_mockups,
    surfaces,
    unpublish_demos,
)

from starpulse import demo

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        (["starpulse/web/src/App.tsx"], [FLOW_VIEW]),
        (["ci/preview.toml"], [FLOW_VIEW]),
        ([".github/workflows/ui-preview.yml"], [FLOW_VIEW]),
        (["starpulse/demo.py"], [FLOW_VIEW]),
        (["design/hub/index.html"], [MOCKUP]),
        (["design/elements/index.html"], [MOCKUP, ELEMENTS]),
        (["starpulse/web/src/style.css"], [FLOW_VIEW, ELEMENTS]),
        (["design/data.js", "starpulse/web/src/Kanban.tsx"], [FLOW_VIEW, MOCKUP]),
        (["starpulse/server.py", "README.md", "starpulse/tests/unit/test_demo.py", ".github/workflows/ci.yml"], []),
    ],
)
def test_surfaces_follow_the_changed_paths(changed: list[str], expected: list[str]) -> None:
    assert surfaces(changed) == expected


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
        (["design/hub/index.html", "design/edit/edit.js", "design/hub/hub.js", "starpulse/server.py"], ["edit", "hub"]),
        (["design/index.html", "design/data.js"], []),
        (["design/elements/index.html", "design/elements/elements.js"], []),
        (["starpulse/web/src/Kanban.tsx"], []),
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
    FLOW_VIEW: [Path("shots/flow-view-star-map.png"), Path("shots/flow-view-kanban.png")],
    MOCKUP: [Path("shots/design-mockup.png")],
}


def test_comment_opens_with_the_marker_so_a_rerun_finds_it() -> None:
    assert comment_body(SHOTS, run_url="https://x/run/1", sha="abcdef1234567").startswith(MARKER + "\n")


def test_comment_embeds_every_screenshot_under_its_surface() -> None:
    body = comment_body(SHOTS, run_url="https://x/run/1", sha="abcdef1234567")
    flow, mock = body.split(f"### {MOCKUP}")
    assert flow.count("![") == 2
    assert "![flow-view-kanban](./shots/flow-view-kanban.png)" in flow
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
        self.comments = {c["id"]: c for c in existing}
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
    note = demo_note(7, ["flow-view.html"])
    assert "(https://trantor-org.github.io/starpulse-demo/pr-7/flow-view.html)" in note
    assert demo_note(7, []) == ""


def test_pr_body_gains_one_demo_section_a_rerun_replaces_and_teardown_removes() -> None:
    once = pr_body_with_demo("Summary.\n", "first")
    twice = pr_body_with_demo(once, "second")
    assert twice.count("<!-- starpulse:ui-demo -->") == 1
    assert "second" in twice and "first" not in twice
    assert pr_body_with_demo(twice, "") == "Summary.\n"


class DemoGh:
    """`gh` as the demo repository sees it: its tree, and the writes made against it."""

    def __init__(self, tree: dict[str, str]) -> None:
        self.tree = tree
        self.writes: list[tuple[str, str, dict]] = []

    def __call__(self, *args: str) -> str:
        if args == ("api", f"repos/{DEMO_REPO}/git/trees/main?recursive=1"):
            return json.dumps({"tree": [{"path": p, "sha": s, "type": "blob"} for p, s in self.tree.items()]})
        method, route = args[2], args[3].removeprefix(f"repos/{DEMO_REPO}/contents/")
        if method == "PUT":
            self.writes.append((method, route, json.loads(Path(args[5]).read_text())))
        else:
            self.writes.append((method, route, dict(a.split("=", 1) for a in args[5::2])))
        return "{}"


def test_publish_writes_each_demo_and_drops_one_the_pr_no_longer_builds(tmp_path: Path) -> None:
    built = tmp_path / "flow-view.html"
    built.write_text("<html>")
    folder = "pr-7"
    gh = DemoGh({f"{folder}/flow-view.html": "old", f"{folder}/design-mockup.html": "gone", "main/flow-view.html": "m"})

    urls = publish_demos(gh, folder, [built], tmp_path / "scratch")

    assert urls == [f"https://trantor-org.github.io/starpulse-demo/{folder}/flow-view.html"]
    assert gh.writes == [
        (
            "PUT",
            f"{folder}/flow-view.html",
            {
                "message": f"Publish {folder}/flow-view.html",
                "content": base64.b64encode(b"<html>").decode(),
                "sha": "old",
            },
        ),
        (
            "DELETE",
            f"{folder}/design-mockup.html",
            {"message": f"Unpublish {folder}/design-mockup.html", "sha": "gone"},
        ),
    ]


def test_unpublish_deletes_only_this_prs_folder() -> None:
    gh = DemoGh({"pr-7/a.html": "a", "pr-70/a.html": "b", "main/a.html": "m"})

    unpublish_demos(gh, "pr-7")

    assert gh.writes == [("DELETE", "pr-7/a.html", {"message": "Unpublish pr-7/a.html", "sha": "a"})]


def test_publishing_main_replaces_mains_demos_and_leaves_every_pr_folder(tmp_path: Path) -> None:
    built = tmp_path / "flow-view.html"
    built.write_text("<html>")
    gh = DemoGh({"main/flow-view.html": "old", "main/gone.html": "g", "pr-7/flow-view.html": "p"})

    urls = publish_demos(gh, MAIN_FOLDER, [built], tmp_path / "scratch")

    assert urls == ["https://trantor-org.github.io/starpulse-demo/main/flow-view.html"]
    assert [(method, route) for method, route, _ in gh.writes] == [
        ("PUT", "main/flow-view.html"),
        ("DELETE", "main/gone.html"),
    ]


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
    clean, leaky = tmp_path / "flow-view.html", tmp_path / "design-mockup.html"
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
    (tmp_path / "flow-view.html").write_text("<html>DEMO-1</html>")
    assert main(["--scan", str(tmp_path)]) == 0
    (tmp_path / "design-mockup.html").write_text("<html>TASK-9</html>")
    assert main(["--scan", str(tmp_path)]) == 1
    assert "design-mockup.html: task id: TASK-9" in capsys.readouterr().err


def test_scan_demos_passes_a_clean_demo(tmp_path: Path) -> None:
    clean = tmp_path / "flow-view.html"
    clean.write_text("<html>DEMO-1</html>")
    scan_demos([clean])
