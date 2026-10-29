"""The page stub the server tests start under: shared by every holder in a checkout, removed with the last one."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from tests.page_stub import held


def _static(tmp_path: Path) -> Path:
    return tmp_path / "static"


def test_a_holder_gets_a_page_and_leaves_the_checkout_as_it_found_it(tmp_path):
    static = _static(tmp_path)
    with held(static):
        assert (static / "index.html").is_file()
    assert not static.exists()


def test_the_page_stays_until_the_last_overlapping_holder_leaves(tmp_path):
    static = _static(tmp_path)
    with held(static):
        with held(static):
            pass
        assert (static / "index.html").is_file()
    assert not static.exists()


def test_a_real_build_is_left_in_place(tmp_path):
    static = _static(tmp_path)
    static.mkdir()
    (static / "index.html").write_text("<html>real</html>")
    with held(static):
        pass
    assert (static / "index.html").read_text() == "<html>real</html>"


def test_a_build_that_replaces_the_stub_while_held_survives_the_last_holder(tmp_path):
    static = _static(tmp_path)
    with held(static):
        (static / "index.html").write_text("<html>real</html>")
        (static / "assets").mkdir()
    assert (static / "index.html").read_text() == "<html>real</html>"
    assert (static / "assets").is_dir()


def test_a_holder_that_died_does_not_keep_the_page(tmp_path):
    static = _static(tmp_path)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (static / ".stub-users").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html>")
    (static / ".stub-users" / f"{dead.pid}-x").touch()
    with held(static):
        pass
    assert not static.exists()


def test_a_holder_in_another_process_keeps_the_page_after_this_one_leaves(tmp_path):
    static = _static(tmp_path)
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import sys
                from pathlib import Path
                from tests.page_stub import held
                with held(Path(sys.argv[1])):
                    print("held", flush=True)
                    sys.stdin.readline()
                """
            ),
            str(static),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "held"
        with held(static):
            pass
        assert (static / "index.html").is_file()
    finally:
        child.communicate("\n", timeout=30)
    assert not static.exists()
