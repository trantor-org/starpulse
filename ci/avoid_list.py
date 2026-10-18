"""Run trantor's glossary avoid-list gate over this repository's context packages and fail on any finding.

Each `context-<slug>` import-linter contract in `pyproject.toml` names a StarPulse context's packages; trantor's glossary
for the slug lists, under each term, the `_Avoid_:` words it replaces. A Python file the diff against `base` changes
inside a context's package fails when an added line introduces a def, class or module-level name holding one of them.
Only added lines count, so existing names never fail. trantor's `linting.avoid_list` does the parsing and matching; the
glossaries are trantor-docs' `governance/architecture`, which this repository does not carry, so a context with no
glossary there is a failure, not a skip.

Usage: python ci/avoid_list.py <trantor>/lib <glossary dir> [base]   (base: the merge base with origin/main)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def _owners(path: str, contexts: dict[str, list[str]]) -> list[str]:
    module = path.removesuffix(".py").replace("/", ".")
    return [slug for slug, packages in contexts.items() if any(module.startswith(f"{p}.") for p in packages)]


def findings(lib: Path, root: Path, glossaries: Path, base: str) -> list[str]:
    """`path:line:` messages for the avoided terms *root*'s change since *base* adds to its contexts' new names."""
    sys.path.insert(0, str(lib))
    from linting import avoid_list

    contexts = avoid_list.context_packages(root)
    messages = []
    for path in _git(root, "diff", "--name-only", "--diff-filter=AM", base, "--", "*.py").splitlines():
        for slug in _owners(path, contexts):
            glossary_path = glossaries / f"{slug}-ubiquitous-language.md"
            if not glossary_path.is_file():
                messages.append(f"{path}: no {slug} glossary at {glossary_path}")
                continue
            glossary = avoid_list.parse_glossary(glossary_path.read_text())
            added = avoid_list.added_lines(_git(root, "diff", "-U0", base, "--", path))
            found = avoid_list.code_findings((root / path).read_text(), added, glossary)
            messages += [f"{path}:{f.line}: '{f.phrase}' is on the {slug} avoid-list; say '{f.preferred}'" for f in found]
    return messages


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[1]
    base = argv[2] if len(argv) > 2 else _git(root, "merge-base", "HEAD", "origin/main").strip()
    messages = findings(Path(argv[0]).resolve(), root, Path(argv[1]).resolve(), base)
    for message in messages:
        print(f"::error::{message}")
    return 1 if messages else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
