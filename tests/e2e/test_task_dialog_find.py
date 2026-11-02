"""The task dialog's closed sections open when the browser searches for a word inside one.

Chromium opens a closed `<details>` when a search matches text inside it, and Playwright cannot drive the browser's
find bar, so the search is a text-fragment navigation (`#:~:text=`), which runs the same match-and-reveal. The page is the
public demo's: the one-file build around a seeded board, whose assigned tasks carry a templated description.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from starpulse.cli import demo

playwright = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e

WEB = Path(demo.__file__).parents[1] / "web"
#: The word sits in the Rollout table's body, never in the section's one-line preview, which is also searchable text.
WORD = "Canary"
SECTIONS_KEY = "fv.task.sections"


@pytest.fixture(scope="module")
def page_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not (demo.STATIC / "index.html").is_file():
        subprocess.run(["pnpm", "run", "build"], cwd=WEB, check=True)
    live = {"now": time.time(), "flows": [{"name": "board", "machine": {}, "agents": []}], "domains": [], "dags": []}
    out = tmp_path_factory.mktemp("find") / "demo.html"
    out.write_text(demo.page(demo.STATIC, demo.scrub(live)))
    return out


def test_a_word_in_a_closed_section_opens_it(page_file: Path) -> None:
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_EXECUTABLE") or None)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{page_file.as_uri()}?demo&view=kanban&task=DEMO-1")
        page.wait_for_selector("details.dsec")
        rollout = page.locator('details.dsec[data-section="Rollout"]')
        assert rollout.evaluate("d => d.open") is False
        assert page.locator('details.dsec[data-section="Scope"]').evaluate("d => d.open") is True

        page.goto(page.url.split("#")[0] + f"#:~:text={WORD}")  # the page rewrites its URL, so this stays in the document

        page.wait_for_function("() => document.querySelector('details.dsec[data-section=Rollout]').open", timeout=5000)
        assert rollout.evaluate("d => d.open") is True
        assert page.evaluate(f"() => JSON.parse(localStorage.getItem('{SECTIONS_KEY}')).Rollout") is True
        browser.close()
