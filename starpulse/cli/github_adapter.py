"""The GitHub adapter's entry point, `python -m starpulse.cli.github_adapter`: `starpulse.pulls.github` given the
runtime's config loader, which no context imports (spec doc-966, D6)."""

from starpulse.pulls.github import main as _main
from starpulse.runtime.config import discover, load

__all__ = ["main"]


def main(argv: list[str] | None = None) -> None:
    _main(argv, discover=discover, load=load)


if __name__ == "__main__":
    main()
