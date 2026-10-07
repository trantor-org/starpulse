"""The public package names no workflow runner: only its Dagu adapter module (and tests) may say `dagu`."""

import re
from pathlib import Path

PACKAGE = next(root for root in Path(__file__).resolve().parents if (root / "board.py").is_file())
RUNNER = re.compile(r"\bdagu\b", re.IGNORECASE)
ADAPTER = {"dagu.py"}


def _sources() -> list[Path]:
    python = [
        p
        for p in PACKAGE.rglob("*.py")
        if p.name not in ADAPTER and not {"tests", "web", "node_modules"} & set(p.relative_to(PACKAGE).parts)
    ]
    pages = [
        p for p in (PACKAGE / "web" / "src").rglob("*.ts*") if ".test." not in p.name and "node_modules" not in p.parts
    ]
    return [*python, *pages]


def test_the_package_outside_its_adapter_names_no_workflow_runner() -> None:
    sources = _sources()

    assert sources, "no sources found: the guard would pass vacuously"
    assert [
        f"{p.relative_to(PACKAGE)}:{n}"
        for p in sources
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if RUNNER.search(line)
    ] == []
