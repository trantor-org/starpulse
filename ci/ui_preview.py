"""Render a pull request's StarPulse UI and post the screenshots as one PR comment; publish main's live demo.

`.github/workflows/ui-preview.yml` runs this on every pull request that touches the page (`starpulse/web/**`), the
design mockup and element sheet (`design/**`) or this preview. A push that changed no such path since the commit the
comment was rendered from leaves the comment and demos as they are. It builds each changed surface's scrubbed
one-file demo with `starpulse._internal.cli.demo`, and each changed sub-mockup (`design/<dir>/index.html`) as `mockup-<dir>.html` with its scripts
inlined, screenshots the demos (of StarPulse, only the views the change can reach), publishes them to the `gh-pages` branch GitHub Pages serves
for this public repository while the pull request is open, and leaves one comment holding the screenshots and the demo links. A push to `main` that
touches the same paths runs it with `--main`, which republishes every demo as `main/`, the live demo and the screenshots the README
links. StarPulse is rendered against `ci/preview.toml`, a demo config naming no real board or runs adapter.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import functools
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any

STARPULSE = "starpulse"
MOCKUP = "design-mockup"
ELEMENTS = "element-sheet"
#: The design directory the element sheet owns; it is a surface of its own, not a sub-mockup, so its stylesheet link is inlined.
ELEMENTS_DIR = "elements"
#: The paths whose change renders each surface; the workflow's `paths` filter is their union.
SURFACE_GLOBS = {
    # the demo's scrub decides what StarPulse's demo can draw
    STARPULSE: (
        "starpulse/web/**",
        "starpulse/_internal/cli/demo.py",
        # of ci/, only what shapes the render: this script and the demo config, adapter and workspace it draws
        "ci/ui_preview.py",
        "ci/preview.toml",
        "ci/demo_workspace.py",
        "ci/workspace/**",
        ".github/workflows/ui-preview.yml",
    ),
    MOCKUP: ("design/**",),
    # the sheet draws the real stylesheet, so a palette change re-renders it too
    ELEMENTS: ("design/elements/**", "starpulse/web/src/style.css"),
}
UI_GLOBS = tuple(dict.fromkeys(g for globs in SURFACE_GLOBS.values() for g in globs))
PREVIEW_CONFIG = "ci/preview.toml"
DESIGN = "design"
#: Each surface's screenshots: a name and the query string the demo file opens with.
PAGES = {
    STARPULSE: {
        "starpulse-star-map": "",
        "starpulse-kanban": "?view=kanban",
        # the task dialog over the Kanban: an assigned task with its plan, and an unassigned one with none
        "starpulse-task": "?view=kanban&task=DEMO-1",
        "starpulse-task-unplanned": "?view=kanban&task=DEMO-2",
        "starpulse-dags": "?view=dags",
    },
    MOCKUP: {"design-mockup": ""},
    ELEMENTS: {"element-sheet": ""},
}
_FEATURES = ("starpulse", "web", "src", "features")
#: The feature folder that draws only its own starpulse pages: a feature imports shared code and its own folder, never another's.
VIEW_DIRS = {
    "kanban": ("starpulse-kanban", "starpulse-task", "starpulse-task-unplanned"),
    "dags": ("starpulse-dags",),
}


def _matches(path: str, glob: str) -> bool:
    return PurePosixPath(path).full_match(glob)


def surfaces(changed: Iterable[str]) -> list[str]:
    """The surfaces to render, in `SURFACE_GLOBS` order: each one a changed path falls under."""
    files = set(changed)
    return [s for s, globs in SURFACE_GLOBS.items() if any(_matches(f, g) for f in files for g in globs)]


def pages(surface: str, changed: Iterable[str]) -> dict[str, str]:
    """The screenshots `surface` takes for a change: every page, or for StarPulse only the views `VIEW_DIRS` says
    own every changed page path. A path outside those folders may draw on any view, so it shoots them all."""
    if surface != STARPULSE:
        return PAGES[surface]
    views = set()
    for parts in (PurePosixPath(f).parts for f in changed if any(_matches(f, g) for g in SURFACE_GLOBS[STARPULSE])):
        if parts[:4] != _FEATURES or len(parts) < 6 or parts[4] not in VIEW_DIRS:
            return PAGES[STARPULSE]
        views.update(VIEW_DIRS[parts[4]])
    return {name: query for name, query in PAGES[STARPULSE].items() if name in views}


def demo_name(surface: str) -> str:
    return f"{surface}.html"


def sub_mockups(changed: Iterable[str]) -> list[str]:
    """The design sub-mockups a change touches: each `design/<dir>/` holding a changed path, sorted, bar the element sheet."""
    dirs = {p.parts[1] for p in map(PurePosixPath, changed) if len(p.parts) > 2 and p.parts[0] == DESIGN}
    return sorted(dirs - {ELEMENTS_DIR})


def sub_mockup_name(directory: str) -> str:
    """The demo `design/<directory>/` publishes as, prefixed so no directory takes the main mockup's name."""
    return f"mockup-{directory}.html"


_LOCAL_SCRIPT = re.compile(r'<script src="([\w.-]+\.js)"></script>')


def sub_mockup(directory: Path) -> str:
    """A sub-mockup's `index.html` with each local script inlined, so the one file is the whole demo.

    A sub-mockup is a scrubbed capture of the page (`starpulse._internal.cli.demo --server`) with its own layer over it, so it is
    published as it is; the leak scan still reads every byte before anything goes out.
    """

    def body(m: re.Match[str]) -> str:
        return "<script>" + (directory / m[1]).read_text().replace("</script", "<\\/script") + "</script>"

    return _LOCAL_SCRIPT.sub(body, (directory / "index.html").read_text())


MARKER = "<!-- starpulse:ui-preview -->"

_CAVEATS = {
    STARPULSE: (
        "Rendered from the scrubbed demo `starpulse._internal.cli.demo` builds off a server running `ci/preview.toml`: "
        "the synthetic workspace in `ci/workspace` (an eight-lane board, its lifecycle machines and five DAG domains) "
        "filled with synthetic tasks, sessions and runs, and no real board or runs adapter behind it."
    ),
    MOCKUP: "Rendered from the scrubbed demo `starpulse._internal.cli.demo --mockup design` builds from the saved mockup data.",
    ELEMENTS: "Rendered from `starpulse._internal.cli.demo --elements design/elements`: the palette tokens and each element, drawn by the real stylesheet.",
}


def _sub_caveat(name: str) -> str:
    return f"Rendered from the sub-mockup `{DESIGN}/{name.removeprefix('mockup-')}/` with its scripts inlined."


def comment_body(shots: Mapping[str, Sequence[Path]], run_url: str, sha: str, demo: str = "") -> str:
    """The one PR comment: each surface's screenshots, as references `gh pr comment --attach` rewrites to uploads.

    `demo` is `demo_note`'s paragraph, shown last under its own heading.
    """
    lines = [
        MARKER,
        f"<!-- rendered: {sha} -->",
        f"## UI preview of `{sha[:7]}`",
        "",
        f"[Run]({run_url}). This render is review context, not an approval.",
    ]
    for surface, paths in shots.items():
        lines += ["", f"### {surface}", _CAVEATS.get(surface) or _sub_caveat(surface), ""]
        lines += [f"![{p.stem}](./{p.as_posix()})" for p in paths]
    if demo:
        lines += ["", "### Demo", demo]
    return "\n".join(lines) + "\n"


def failure_body(run_url: str, sha: str) -> str:
    """The one PR comment when the render failed: no screenshots, the run to read, and no `rendered` commit.

    It carries no `<!-- rendered: -->` line, so `rendered_sha` finds none and the next push renders again.
    """
    return (
        f"{MARKER}\n## UI preview of `{sha[:7]}` failed\n\n"
        f"The render did not finish, so this pull request has no screenshots or demos for that commit. "
        f"See [the run]({run_url}). This preview never gates the pull request.\n"
    )


def find_comment(comments: Sequence[Mapping[str, Any]], author: str) -> int | None:
    """The id of `author`'s earlier preview comment, if this PR has one."""
    return next(
        (c["id"] for c in comments if c["user"]["login"] == author and c["body"].startswith(MARKER)),
        None,
    )


_RENDERED = re.compile(r"<!-- rendered: ([0-9a-f]{40}) -->")
#: The most files GitHub's comparison lists; a full list may be cut short.
_COMPARE_FILES = 300


def rendered_sha(comments: Sequence[Mapping[str, Any]], author: str) -> str | None:
    """The commit `author`'s preview comment on this PR says it was rendered from, if there is one."""
    found = find_comment(comments, author)
    match = next((_RENDERED.search(c["body"]) for c in comments if c["id"] == found), None)
    return match[1] if match else None


def push_touches_ui(compare: Mapping[str, Any] | None) -> bool:
    """Whether the commits since the last render need a new one, given GitHub's comparison of that render's commit to the head.

    Only a fast-forward whose whole file list misses every UI path needs none. A rebase or force-push can carry
    main's UI changes, and a missing or cut-short comparison vouches for nothing, so those render.
    """
    if not compare or compare["status"] != "ahead" or len(compare["files"]) >= _COMPARE_FILES:
        return True
    return bool(surfaces(name for f in compare["files"] for name in (f["filename"], f.get("previous_filename")) if name))


def publish(gh: Callable[..., str], repo: str, pr: int, body: Path, images: Sequence[Path], author: str) -> str:
    """Leave `author`'s one preview comment on the PR, holding `body` with `images` uploaded; returns its URL.

    Only `gh pr comment --attach` uploads an image, and it only creates. A rerun therefore posts the new comment,
    copies its body (now pointing at the uploads) into the earlier preview comment, and deletes the new one.
    """
    attach = [arg for image in images for arg in ("--attach", image.as_posix())]
    created = gh("pr", "comment", str(pr), "--repo", repo, "--body-file", body.as_posix(), *attach).strip()
    new_id = int(created.rsplit("issuecomment-", 1)[1])
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/issues/{pr}/comments"))
    earlier = [c for page in pages for c in page if c["id"] != new_id]
    old_id = find_comment(earlier, author)
    if old_id is None:
        return created
    uploaded = json.loads(gh("api", f"repos/{repo}/issues/comments/{new_id}"))["body"]
    gh("api", "--method", "PATCH", f"repos/{repo}/issues/comments/{old_id}", "-f", f"body={uploaded}")
    gh("api", "--method", "DELETE", f"repos/{repo}/issues/comments/{new_id}")
    return next(c["html_url"] for c in earlier if c["id"] == old_id)


def publish_failure(gh: Callable[..., str], repo: str, pr: int, body: str, author: str) -> None:
    """Put `body` in `author`'s one preview comment, editing the earlier one in place or creating it."""
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/issues/{pr}/comments"))
    old_id = find_comment([c for page in pages for c in page], author)
    if old_id is None:
        gh("api", "--method", "POST", f"repos/{repo}/issues/{pr}/comments", "-f", f"body={body}")
    else:
        gh("api", "--method", "PATCH", f"repos/{repo}/issues/comments/{old_id}", "-f", f"body={body}")


#: The public repository whose GitHub Pages site serves the demos, from its `gh-pages` branch.
DEMO_REPO = "trantor-org/starpulse"
#: The branch GitHub Pages serves the demos from.
DEMO_BRANCH = "gh-pages"
#: The folder in it that always holds main's demos.
MAIN_FOLDER = "main"
#: `--touches` exit status for a change that reaches no UI path; any other non-zero status is an error.
NO_UI = 3
#: The hosts a public demo may link to: XML namespaces, the mockup's web font and React's error decoder.
DEMO_URL_HOSTS = frozenset({"www.w3.org", "fonts.googleapis.com", "fonts.gstatic.com", "react.dev", "example.com"})
#: Single URLs a bundled library prints on another host, allowed without allowing the host: the Kanban nickname
#: library's migration-guide link in its error text.
DEMO_URLS = ("https://github.com/andreasonny83/unique-names-generator",)
#: Identifiers the scrub must have removed, by the name a refusal gives them. The scrub's own synthetic UUIDs
#: (`starpulse._internal.cli.demo`) are `<n>-0000-4000-8000-000000000000`, so only those pass.
LEAK_PATTERNS = {
    "task id": re.compile(r"\bTASK-\d+"),
    "private address": re.compile(r"\b(?:(?:10|127)\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
    "uuid": re.compile(
        r"\b(?![0-9a-f]{8}-0000-4000-8000-000000000000)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        re.IGNORECASE,
    ),
    "session id": re.compile(r"\bsession_[A-Za-z0-9]{16,}"),
    "email": re.compile(r"\b[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b"),
    "home path": re.compile(r"/(?:home|Users)/\w+|/root/"),
    "token": re.compile(r"\b(?:gh[pousr]_\w{20,}|github_pat_\w{20,}|sk-[\w-]{20,})"),
}
_URL_HOST = re.compile(r"https?://([^/\s\"'`<>)\\:?#]+)")


def demo_folder(pr: int) -> str:
    """The Pages folder a pull request's demos live in while it is open."""
    return f"pr-{pr}"


def demo_url(folder: str, name: str) -> str:
    owner, repo = DEMO_REPO.split("/")
    return f"https://{owner}.github.io/{repo}/{folder}/{name}"


def demo_note(pr: int, names: Sequence[str]) -> str:
    """The paragraph linking the PR's public demos."""
    if not names:
        return ""
    links = ", ".join(f"[{n}]({demo_url(demo_folder(pr), n)})" for n in names)
    return f"Public scrubbed demo: {links}. Merging or closing the PR unpublishes it."


DEMO_SECTION = re.compile(r"\n*<!-- starpulse:ui-demo -->.*?<!-- /starpulse:ui-demo -->\n?", re.DOTALL)


def pr_body_with_demo(body: str, note: str) -> str:
    """The PR description with its one demo section replaced by `note`, or removed when `note` is empty."""
    body = DEMO_SECTION.sub("", body).rstrip("\n") + "\n"
    if not note:
        return body
    return f"{body}\n<!-- starpulse:ui-demo -->\n## Demo\n\n{note}\n<!-- /starpulse:ui-demo -->\n"


class DemoLeakError(RuntimeError):
    """A demo still carries a real identifier, so nothing is published."""


def leaks(text: str) -> list[str]:
    """Each distinct real identifier in a demo, as `<kind>: <match>`; empty when the scrub held."""
    hits = {f"{kind}: {m.group()}" for kind, pattern in LEAK_PATTERNS.items() for m in pattern.finditer(text)}
    urls = [m for m in _URL_HOST.finditer(text) if m.group(1) not in DEMO_URL_HOSTS]
    hits |= {f"url: {m.group()}" for m in urls if not text.startswith(DEMO_URLS, m.start())}
    return sorted(hits)


def scan_demos(files: Sequence[Path]) -> None:
    """Raise `DemoLeakError` naming every real identifier the demos still carry; return when they are clean."""
    found = [f"{f.name}: {hit}" for f in files for hit in leaks(f.read_text(errors="replace"))]
    if found:
        raise DemoLeakError("refusing to publish a demo that leaks:\n" + "\n".join(found))


def _published(gh: Callable[..., str], folder: str) -> dict[str, str]:
    tree = json.loads(gh("api", f"repos/{DEMO_REPO}/git/trees/{DEMO_BRANCH}?recursive=1"))["tree"]
    return {t["path"]: t["sha"] for t in tree if t["path"].startswith(f"{folder}/")}


#: Concurrent runs commit to the one Pages branch; GitHub answers the loser `is at X but expected Y (HTTP 409)`.
_CONFLICT_ATTEMPTS = 4
#: One lock for every run on this host, so their Pages-branch writes take turns and no burst races the 4 attempts.
_PAGES_LOCK = Path(tempfile.gettempdir()) / "sp-preview-pages.lock"


@contextmanager
def _pages_turn() -> Iterator[None]:
    """Hold the Pages lock while a run reads and writes the branch; another run waits its turn."""
    with _PAGES_LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _retry_conflict(write: Callable[[], str]) -> None:
    """Run a Pages-branch write, repeating it while another run's commit keeps moving the branch."""
    for attempt in range(1, _CONFLICT_ATTEMPTS + 1):
        try:
            write()
        except RuntimeError as error:
            if "HTTP 409" not in str(error) or attempt == _CONFLICT_ATTEMPTS:
                raise
            time.sleep(attempt)
        else:
            return


def _blob_sha(gh: Callable[..., str], route: str) -> str | None:
    """The sha of the file at `route` on the Pages branch, or None when no run has committed it there."""
    try:
        return gh("api", f"{route}?ref={DEMO_BRANCH}", "--jq", ".sha").strip()
    except RuntimeError:
        return None


def _put_demo(gh: Callable[..., str], path: str, body: dict[str, Any], request: Path) -> None:
    """Commit one demo, taking the file's current sha again when another run landed it or moved it under the write."""
    route = f"repos/{DEMO_REPO}/contents/{path}"
    conflicted = False
    for attempt in range(1, _CONFLICT_ATTEMPTS + 1):
        request.write_text(json.dumps(body))
        try:
            gh("api", "--method", "PUT", route, "--input", request.as_posix())
        except RuntimeError as error:
            if attempt == _CONFLICT_ATTEMPTS or not ("wasn't supplied" in str(error) or "HTTP 409" in str(error)):
                raise
            conflicted = conflicted or "HTTP 409" in str(error)
            time.sleep(attempt)
            current = _blob_sha(gh, route)
            body.pop("sha", None)
            if current:
                body["sha"] = current
        else:
            if conflicted:
                print(f"sp-preview recovered HTTP 409 on {route} after {attempt} attempts", file=sys.stderr)
            return


def _delete(gh: Callable[..., str], path: str, sha: str) -> None:
    route = f"repos/{DEMO_REPO}/contents/{path}"
    fields = (f"message=Unpublish {path}", f"sha={sha}", f"branch={DEMO_BRANCH}")
    _retry_conflict(lambda: gh("api", "--method", "DELETE", route, *(arg for field in fields for arg in ("-f", field))))


def _branch_exists(gh: Callable[..., str]) -> bool:
    try:
        gh("api", f"repos/{DEMO_REPO}/branches/{DEMO_BRANCH}")
    except RuntimeError:
        return False
    return True


def _create_branch(gh: Callable[..., str], scratch: Path) -> None:
    """Create the Pages branch as a root commit holding only `.nojekyll`, so Pages serves the files as they are."""
    scratch.mkdir(parents=True, exist_ok=True)

    def post(route: str, body: dict[str, Any]) -> dict[str, Any]:
        request = scratch / "branch.json"
        request.write_text(json.dumps(body))
        created = gh("api", "--method", "POST", f"repos/{DEMO_REPO}/git/{route}", "--input", request.as_posix())
        return json.loads(created)

    tree = post("trees", {"tree": [{"path": ".nojekyll", "mode": "100644", "type": "blob", "content": "\n"}]})["sha"]
    commit = post("commits", {"message": "Create the Pages branch", "tree": tree, "parents": []})["sha"]
    post("refs", {"ref": f"refs/heads/{DEMO_BRANCH}", "sha": commit})


def publish_demos(gh: Callable[..., str], folder: str, files: Sequence[Path], scratch: Path) -> list[str]:
    """Commit each demo to `folder` in the Pages repository, dropping any it no longer builds; returns their URLs.

    Every page is scanned first, and one leak refuses the whole publish before anything is written; a screenshot
    is of a scanned page, and its bytes are not text. The contents
    API takes a file per request, and a demo is too large for an argument, so each body goes through a file in
    `scratch`.
    """
    scan_demos([f for f in files if f.suffix == ".html"])
    with _pages_turn():
        if not _branch_exists(gh):
            _create_branch(gh, scratch)
        old = _published(gh, folder)
        scratch.mkdir(parents=True, exist_ok=True)
        paths = []
        for f in files:
            path = f"{folder}/{f.name}"
            body = {"message": f"Publish {path}", "content": base64.b64encode(f.read_bytes()).decode(), "branch": DEMO_BRANCH}
            if path in old:
                body["sha"] = old[path]
            _put_demo(gh, path, body, scratch / f"{f.name}.json")
            paths.append(path)
        for path in sorted(old.keys() - set(paths)):
            _delete(gh, path, old[path])
    return [demo_url(folder, f.name) for f in files]


def unpublish_demos(gh: Callable[..., str], folder: str) -> None:
    """Remove every file under `folder` from the Pages branch; a repository without one has none."""
    with _pages_turn():
        if not _branch_exists(gh):
            return
        for path, sha in sorted(_published(gh, folder).items()):
            _delete(gh, path, sha)


# Everything below drives processes (GitHub, the server, a browser); the pure rules above carry the tests.

_PLAYWRIGHT_CLI = ("pnpm", "dlx", "@playwright/cli@0.1.22")
_VIEWPORT = (1600, 1000)
#: How long a page gets to draw after it opens; StarPulse's machines settle within a few seconds.
_SETTLE_MS = 10000


def _run(*cmd: str, env: Mapping[str, str] | None = None) -> str:  # pragma: no cover — process boundary
    done = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=900, env=env)
    if done.returncode:
        raise RuntimeError(f"`{' '.join(cmd[:4])}` exited {done.returncode}: {done.stderr.strip()}")
    return done.stdout


def _gh(*args: str) -> str:  # pragma: no cover — process boundary
    return _run("gh", *args)


def _demo_gh(*args: str) -> str:  # pragma: no cover — process boundary
    """`gh` as the run's own token, `DEMO_TOKEN`, which writes the Pages branch; the comment posts as another user."""
    return _run("gh", *args, env={**os.environ, "GH_TOKEN": os.environ["DEMO_TOKEN"]})


def _free_port() -> int:  # pragma: no cover — process boundary
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_ready(url: str, seconds: float) -> None:  # pragma: no cover — process boundary
    """Block until `url` answers 200, a bounded wait for a server this script just started."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except OSError:
            if time.monotonic() > deadline:
                raise
        time.sleep(2)


@contextmanager
def _starpulse() -> Iterator[int]:  # pragma: no cover — process boundary
    """A server on `PREVIEW_CONFIG`, using its isolated preview database."""
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URI"}
    server = subprocess.Popen(
        [sys.executable, "-m", "starpulse.runtime.server", "--port", str(port), "--config", PREVIEW_CONFIG], env=env
    )
    try:
        _wait_ready(f"http://127.0.0.1:{port}/api/snapshot", 180)
        yield port
    finally:
        server.terminate()
        server.wait(timeout=30)


def _build_demos(names: Sequence[str], out: Path) -> list[Path]:  # pragma: no cover — process boundary
    out.mkdir(parents=True, exist_ok=True)
    built = []
    if demo_name(STARPULSE) in names:
        with _starpulse() as port:
            target = out / demo_name(STARPULSE)
            _run(sys.executable, "-m", "starpulse._internal.cli.demo", "--server", f"http://127.0.0.1:{port}", "--out", str(target))
            built.append(target)
    if demo_name(MOCKUP) in names:
        target = out / demo_name(MOCKUP)
        _run(sys.executable, "-m", "starpulse._internal.cli.demo", "--mockup", DESIGN, "--out", str(target))
        built.append(target)
    if demo_name(ELEMENTS) in names:
        target = out / demo_name(ELEMENTS)
        _run(sys.executable, "-m", "starpulse._internal.cli.demo", "--elements", f"{DESIGN}/{ELEMENTS_DIR}", "--out", str(target))
        built.append(target)
    return built


def _build_sub_mockups(directories: Sequence[str], out: Path) -> list[Path]:  # pragma: no cover — file boundary
    built = []
    for d in directories:
        if (Path(DESIGN) / d / "index.html").is_file():  # a deleted sub-mockup builds nothing
            target = out / sub_mockup_name(d)
            target.write_text(sub_mockup(Path(DESIGN) / d))
            built.append(target)
    return built


@contextmanager
def _serve(directory: Path) -> Iterator[int]:  # pragma: no cover — process boundary
    """Serve `directory` over HTTP: a demo opened as `file://` fails its module script."""
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(directory))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield httpd.server_address[1]
    finally:
        httpd.shutdown()


#: Extra tries after the first when a playwright-cli call exits non-zero; the shared daemon sometimes answers `Session closed`.
_SHOOT_RETRIES = 2


def _shoot(url: str, out: Path) -> Path:
    """Open `url` in headless Chromium, give it `_SETTLE_MS` to draw, and save the viewport to `out`."""
    # every runner on the host shares one playwright-cli daemon, so a session named per process keeps a concurrent job's `close` off this browser
    pw = [*_PLAYWRIGHT_CLI, f"-s=starpulse-ui-preview-{os.getpid()}"]
    for attempt in range(_SHOOT_RETRIES + 1):
        try:
            _run(*pw, "open", url)
            _run(*pw, "resize", *map(str, _VIEWPORT))
            _run(*pw, "run-code", f"async page => {{ await page.waitForTimeout({_SETTLE_MS}); }}")
            _run(*pw, "screenshot", f"--filename={out.resolve().as_posix()}")
            return out
        except RuntimeError:
            if attempt == _SHOOT_RETRIES:
                raise
        finally:
            _run(*pw, "close")
    raise AssertionError("unreachable")


def _compare(repo: str, base: str, head: str) -> dict[str, Any] | None:  # pragma: no cover — process boundary
    """GitHub's comparison of `base` to `head`, or None when it has none: a force-push can leave `base` unreachable."""
    try:
        return json.loads(_gh("api", f"repos/{repo}/compare/{base}...{head}"))
    except RuntimeError:
        return None


def _set_demo_section(repo: str, pr: int, note: str, scratch: Path) -> None:  # pragma: no cover — process boundary
    body = _gh("pr", "view", str(pr), "--repo", repo, "--json", "body", "--jq", ".body")
    scratch.mkdir(parents=True, exist_ok=True)
    edited = scratch / "pr-body.json"
    edited.write_text(json.dumps({"body": pr_body_with_demo(body, note)}))
    # REST, not `gh pr edit`: its GraphQL query needs read:org, which the runner's token lacks.
    _gh("api", "-X", "PATCH", f"repos/{repo}/pulls/{pr}", "--input", str(edited), "--silent")


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover — process boundary
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--scan", type=Path, metavar="DIR", help="leak-scan the demos built into DIR, publishing nothing"
    )
    parser.add_argument(
        "--touches",
        type=Path,
        metavar="FILE",
        help=f"print the surfaces the changed paths in FILE reach, exiting {NO_UI} when none, rendering nothing",
    )
    parser.add_argument("--main", action="store_true", help="publish this checkout's demos as main's live demo")
    parser.add_argument("--repo", help="owner/name")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--sha")
    parser.add_argument("--run-url")
    parser.add_argument("--failed", action="store_true", help="comment that the pull request's render failed, rendering nothing")
    parser.add_argument("--action", help="the pull_request event's action")
    parser.add_argument("--out", type=Path, default=Path(".tmp/ui-preview"), help="where screenshots and demos go")
    args = parser.parse_args(argv)
    if args.touches:
        reached = surfaces(args.touches.read_text().split())
        if not reached:
            return NO_UI
        print(*reached, sep="\n")
        return 0
    if args.scan:
        try:
            scan_demos(sorted(args.scan.glob("*.html")))
        except DemoLeakError as error:
            print(error, file=sys.stderr)
            return 1
        return 0
    if args.main:
        built = _build_demos([demo_name(s) for s in SURFACE_GLOBS], args.out / "demo")
        with _serve(args.out / "demo") as port:  # the README shows these
            shots = [
                _shoot(f"http://127.0.0.1:{port}/{demo_name(STARPULSE)}{query}", args.out / "demo" / f"{name}.png")
                for name, query in PAGES[STARPULSE].items()
            ]
        print(*publish_demos(_demo_gh, MAIN_FOLDER, built + shots, args.out / "requests"), sep="\n")
        return 0
    if None in (args.repo, args.pr, args.sha, args.run_url, args.action):
        parser.error("a pull request preview needs --repo, --pr, --sha, --run-url and --action")

    if args.failed:
        author = _gh("api", "user", "--jq", ".login").strip()
        publish_failure(_gh, args.repo, args.pr, failure_body(args.run_url, args.sha), author)
        return 0
    folder = demo_folder(args.pr)
    if args.action == "closed":
        unpublish_demos(_demo_gh, folder)
        _set_demo_section(args.repo, args.pr, "", args.out)
        print(f"unpublished {demo_url(folder, '')}")
        return 0
    changed = _gh("api", "--paginate", f"repos/{args.repo}/pulls/{args.pr}/files", "--jq", ".[].filename").split()
    todo = surfaces(changed)
    if not todo:
        print("no UI surface to render")
        return 0
    author = _gh("api", "user", "--jq", ".login").strip()
    comments = json.loads(_gh("api", "--paginate", "--slurp", f"repos/{args.repo}/issues/{args.pr}/comments"))
    last = rendered_sha([c for page in comments for c in page], author)
    if last and not push_touches_ui(_compare(args.repo, last, args.sha)):
        print(f"no UI path changed since the render of {last[:7]}; its comment and demos stand")
        return 0
    demo_dir = args.out / "demo"  # the workflow uploads this directory as the `ui-demo` artifact
    names = [demo_name(s) for s in todo]
    built = _build_demos(names, demo_dir)
    subs = _build_sub_mockups(sub_mockups(changed), demo_dir)
    shots: dict[str, list[Path]] = {}
    with _serve(demo_dir) as port:
        for surface in todo:
            shots[surface] = [
                _shoot(f"http://127.0.0.1:{port}/{demo_name(surface)}{query}", args.out / f"{name}.png")
                for name, query in pages(surface, changed).items()
            ]
        for sub in subs:
            shots[sub.stem] = [_shoot(f"http://127.0.0.1:{port}/{sub.name}", args.out / f"{sub.stem}.png")]
    print(*publish_demos(_demo_gh, folder, built + subs, args.out / "requests"), sep="\n")
    note = demo_note(args.pr, names + [sub.name for sub in subs])
    _set_demo_section(args.repo, args.pr, note, args.out)
    body = args.out / "body.md"
    body.write_text(comment_body(shots, args.run_url, args.sha, note))
    images = [p for paths in shots.values() for p in paths]
    print(publish(_gh, args.repo, args.pr, body, images, author))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
