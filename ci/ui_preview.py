"""Render a pull request's StarPulse UI and post the screenshots as one PR comment; publish main's live demo.

`.github/workflows/ui-preview.yml` runs this on every pull request that touches the page (`starpulse/web/**`), the
design mockup and element sheet (`design/**`) or this preview. It builds each changed surface's scrubbed one-file demo with
`starpulse._internal.cli.demo`, and each changed sub-mockup (`design/<dir>/index.html`) as `mockup-<dir>.html` with its scripts
inlined, screenshots the demos, publishes them to the public `starpulse-demo` Pages repository while the
pull request is open, and leaves one comment holding the screenshots and the demo links. A push to `main` that
touches the same paths runs it with `--main`, which republishes every demo as `main/`, the live demo and the screenshots the README
links. The flow view is rendered against `ci/preview.toml`, a demo config naming no real board or runs adapter.
"""

from __future__ import annotations

import argparse
import base64
import functools
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any

FLOW_VIEW = "flow-view"
MOCKUP = "design-mockup"
ELEMENTS = "element-sheet"
#: The design directory the element sheet owns; it is a surface of its own, not a sub-mockup, so its stylesheet link is inlined.
ELEMENTS_DIR = "elements"
#: The paths whose change renders each surface; the workflow's `paths` filter is their union.
SURFACE_GLOBS = {
    # the demo's scrub decides what the flow view's demo can draw
    FLOW_VIEW: ("starpulse/web/**", "starpulse/_internal/cli/demo.py", "ci/**", ".github/workflows/ui-preview.yml"),
    MOCKUP: ("design/**",),
    # the sheet draws the real stylesheet, so a palette change re-renders it too
    ELEMENTS: ("design/elements/**", "starpulse/web/src/style.css"),
}
UI_GLOBS = tuple(dict.fromkeys(g for globs in SURFACE_GLOBS.values() for g in globs))
PREVIEW_CONFIG = "ci/preview.toml"
DESIGN = "design"
#: Each surface's screenshots: a name and the query string the demo file opens with.
PAGES = {
    FLOW_VIEW: {
        "flow-view-star-map": "",
        "flow-view-kanban": "?view=kanban",
        "flow-view-orbit": "?view=graph",
        "flow-view-dags": "?view=dags",
    },
    MOCKUP: {"design-mockup": ""},
    ELEMENTS: {"element-sheet": ""},
}


def _matches(path: str, glob: str) -> bool:
    return PurePosixPath(path).full_match(glob)


def surfaces(changed: Iterable[str]) -> list[str]:
    """The surfaces to render, in `SURFACE_GLOBS` order: each one a changed path falls under."""
    files = set(changed)
    return [s for s, globs in SURFACE_GLOBS.items() if any(_matches(f, g) for f in files for g in globs)]


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
    FLOW_VIEW: (
        "Rendered from the scrubbed demo `starpulse._internal.cli.demo` builds off a server running `ci/preview.toml`: "
        "the synthetic workspace in `ci/workspace` (a nine-lane board, its lifecycle machines and five DAG domains) "
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


def find_comment(comments: Sequence[Mapping[str, Any]], author: str) -> int | None:
    """The id of `author`'s earlier preview comment, if this PR has one."""
    return next(
        (c["id"] for c in comments if c["user"]["login"] == author and c["body"].startswith(MARKER)),
        None,
    )


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


#: The public GitHub Pages repository the demos are published to.
DEMO_REPO = "trantor-org/starpulse-demo"
#: The folder in it that always holds main's demos.
MAIN_FOLDER = "main"
#: The hosts a public demo may link to: XML namespaces, the mockup's web font and React's error decoder.
DEMO_URL_HOSTS = frozenset({"www.w3.org", "fonts.googleapis.com", "fonts.gstatic.com", "react.dev"})
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
    hits |= {f"url: {m.group()}" for m in _URL_HOST.finditer(text) if m.group(1) not in DEMO_URL_HOSTS}
    return sorted(hits)


def scan_demos(files: Sequence[Path]) -> None:
    """Raise `DemoLeakError` naming every real identifier the demos still carry; return when they are clean."""
    found = [f"{f.name}: {hit}" for f in files for hit in leaks(f.read_text(errors="replace"))]
    if found:
        raise DemoLeakError("refusing to publish a demo that leaks:\n" + "\n".join(found))


def _published(gh: Callable[..., str], folder: str) -> dict[str, str]:
    tree = json.loads(gh("api", f"repos/{DEMO_REPO}/git/trees/main?recursive=1"))["tree"]
    return {t["path"]: t["sha"] for t in tree if t["path"].startswith(f"{folder}/")}


def _delete(gh: Callable[..., str], path: str, sha: str) -> None:
    route = f"repos/{DEMO_REPO}/contents/{path}"
    gh("api", "--method", "DELETE", route, "-f", f"message=Unpublish {path}", "-f", f"sha={sha}")


def publish_demos(gh: Callable[..., str], folder: str, files: Sequence[Path], scratch: Path) -> list[str]:
    """Commit each demo to `folder` in the Pages repository, dropping any it no longer builds; returns their URLs.

    Every page is scanned first, and one leak refuses the whole publish before anything is written; a screenshot
    is of a scanned page, and its bytes are not text. The contents
    API takes a file per request, and a demo is too large for an argument, so each body goes through a file in
    `scratch`.
    """
    scan_demos([f for f in files if f.suffix == ".html"])
    old = _published(gh, folder)
    scratch.mkdir(parents=True, exist_ok=True)
    paths = []
    for f in files:
        path = f"{folder}/{f.name}"
        body = {"message": f"Publish {path}", "content": base64.b64encode(f.read_bytes()).decode()}
        if path in old:
            body["sha"] = old[path]
        request = scratch / f"{f.name}.json"
        request.write_text(json.dumps(body))
        gh("api", "--method", "PUT", f"repos/{DEMO_REPO}/contents/{path}", "--input", request.as_posix())
        paths.append(path)
    for path in sorted(old.keys() - set(paths)):
        _delete(gh, path, old[path])
    return [demo_url(folder, f.name) for f in files]


def unpublish_demos(gh: Callable[..., str], folder: str) -> None:
    """Remove every file under `folder` from the Pages repository."""
    for path, sha in sorted(_published(gh, folder).items()):
        _delete(gh, path, sha)


# Everything below drives processes (GitHub, the server, a browser); the pure rules above carry the tests.

_PLAYWRIGHT_CLI = ("pnpm", "dlx", "@playwright/cli@0.1.22")
_VIEWPORT = (1600, 1000)
#: How long a page gets to draw after it opens; the flow view's machines settle within a few seconds.
_SETTLE_MS = 10000


def _run(*cmd: str, env: Mapping[str, str] | None = None) -> str:  # pragma: no cover — process boundary
    done = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=900, env=env)
    if done.returncode:
        raise RuntimeError(f"`{' '.join(cmd[:4])}` exited {done.returncode}: {done.stderr.strip()}")
    return done.stdout


def _gh(*args: str) -> str:  # pragma: no cover — process boundary
    return _run("gh", *args)


def _demo_gh(*args: str) -> str:  # pragma: no cover — process boundary
    """`gh` as the workspace App, whose token `DEMO_TOKEN` alone may write the demo repository."""
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
def _flow_view() -> Iterator[int]:  # pragma: no cover — process boundary
    """A server on `PREVIEW_CONFIG`, using its isolated preview database."""
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URI"}
    server = subprocess.Popen(
        [sys.executable, "-m", "starpulse._internal.server.server", "--port", str(port), "--config", PREVIEW_CONFIG], env=env
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
    if demo_name(FLOW_VIEW) in names:
        with _flow_view() as port:
            target = out / demo_name(FLOW_VIEW)
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


def _shoot(url: str, out: Path) -> Path:  # pragma: no cover — process boundary
    """Open `url` in headless Chromium, give it `_SETTLE_MS` to draw, and save the viewport to `out`."""
    # every runner on the host shares one playwright-cli daemon, so a session named per process keeps a concurrent job's `close` off this browser
    pw = [*_PLAYWRIGHT_CLI, f"-s=starpulse-ui-preview-{os.getpid()}"]
    try:
        _run(*pw, "open", url)
        _run(*pw, "resize", *map(str, _VIEWPORT))
        _run(*pw, "run-code", f"async page => {{ await page.waitForTimeout({_SETTLE_MS}); }}")
        _run(*pw, "screenshot", f"--filename={out.resolve().as_posix()}")
    finally:
        _run(*pw, "close")
    return out


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
    parser.add_argument("--main", action="store_true", help="publish this checkout's demos as main's live demo")
    parser.add_argument("--repo", help="owner/name")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--sha")
    parser.add_argument("--run-url")
    parser.add_argument("--action", help="the pull_request event's action")
    parser.add_argument("--out", type=Path, default=Path(".tmp/ui-preview"), help="where screenshots and demos go")
    args = parser.parse_args(argv)
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
                _shoot(f"http://127.0.0.1:{port}/{demo_name(FLOW_VIEW)}{query}", args.out / "demo" / f"{name}.png")
                for name, query in PAGES[FLOW_VIEW].items()
            ]
        print(*publish_demos(_demo_gh, MAIN_FOLDER, built + shots, args.out / "requests"), sep="\n")
        return 0
    if None in (args.repo, args.pr, args.sha, args.run_url, args.action):
        parser.error("a pull request preview needs --repo, --pr, --sha, --run-url and --action")

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
    demo_dir = args.out / "demo"  # the workflow uploads this directory as the `ui-demo` artifact
    names = [demo_name(s) for s in todo]
    built = _build_demos(names, demo_dir)
    subs = _build_sub_mockups(sub_mockups(changed), demo_dir)
    shots: dict[str, list[Path]] = {}
    with _serve(demo_dir) as port:
        for surface in todo:
            shots[surface] = [
                _shoot(f"http://127.0.0.1:{port}/{demo_name(surface)}{query}", args.out / f"{name}.png")
                for name, query in PAGES[surface].items()
            ]
        for sub in subs:
            shots[sub.stem] = [_shoot(f"http://127.0.0.1:{port}/{sub.name}", args.out / f"{sub.stem}.png")]
    print(*publish_demos(_demo_gh, folder, built + subs, args.out / "requests"), sep="\n")
    note = demo_note(args.pr, names + [sub.name for sub in subs])
    _set_demo_section(args.repo, args.pr, note, args.out)
    body = args.out / "body.md"
    body.write_text(comment_body(shots, args.run_url, args.sha, note))
    images = [p for paths in shots.values() for p in paths]
    author = _gh("api", "user", "--jq", ".login").strip()
    print(publish(_gh, args.repo, args.pr, body, images, author))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
