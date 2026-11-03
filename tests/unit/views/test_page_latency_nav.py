"""The page-latency bench clicks nav buttons by title: each must still be a title the page draws."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _views() -> dict[str, str]:
    spec = importlib.util.spec_from_file_location("page_latency", ROOT / "bench" / "page_latency.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.VIEWS


def test_every_view_the_bench_switches_to_is_a_nav_button_the_page_draws() -> None:
    app = (ROOT / "starpulse" / "web" / "src" / "App.tsx").read_text()
    missing = [title for title in _views().values() if f'title="{title}"' not in app and f'"{title}"' not in app]
    assert missing == []
