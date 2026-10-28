"""`serve` and `worker api` listen where the config says, a flag overrides its key, and no key keeps the defaults."""

from pathlib import Path

import pytest

from starpulse.runtime.config import load
from starpulse.runtime.server import resolve_listen, serve_parser
from starpulse.runtime.worker import worker_parser

CONFIG = 'host = "0.0.0.0"\nport = 9000\nhours = 12\n'


def _listening(parser, argv: list[str], config_text: str | None, tmp_path: Path) -> tuple[str, int, float]:
    path = None
    if config_text is not None:
        path = tmp_path / "starpulse.toml"
        path.write_text(config_text)
    args = parser.parse_args(argv)
    resolve_listen(args, load(path))
    return args.host, args.port, args.hours


@pytest.mark.parametrize("parser", [serve_parser(), worker_parser()], ids=["serve", "worker api"])
@pytest.mark.parametrize(
    ("flags", "config_text", "expected"),
    [
        ([], CONFIG, ("0.0.0.0", 9000, 12.0)),
        (["--host", "10.0.0.1", "--port", "9100", "--hours", "1"], CONFIG, ("10.0.0.1", 9100, 1.0)),
        (["--port", "9100"], CONFIG, ("0.0.0.0", 9100, 12.0)),
        ([], None, ("127.0.0.1", 8766, 6.0)),
        (["--port", "9100"], None, ("127.0.0.1", 9100, 6.0)),
    ],
    ids=["config only", "flags override", "one flag overrides", "neither", "flag without config"],
)
def test_listen_options_come_from_a_flag_then_the_config_then_the_defaults(
    parser, flags: list[str], config_text: str | None, expected: tuple[str, int, float], tmp_path: Path
) -> None:
    argv = ["api", *flags] if parser.prog.endswith("worker") else flags

    assert _listening(parser, argv, config_text, tmp_path) == expected


@pytest.mark.parametrize(
    ("line", "refusal"),
    [
        ('host = ""', "host must be an address"),
        ("host = 1", "host must be an address"),
        ("port = 0", "port must be a whole number from 1 to 65535"),
        ("port = 70000", "port must be a whole number from 1 to 65535"),
        ("port = true", "port must be a whole number from 1 to 65535"),
        ("hours = 0", "hours must be a number of hours above 0"),
        ('hours = "6"', "hours must be a number of hours above 0"),
    ],
)
def test_a_listen_key_that_is_not_an_address_port_or_hours_is_refused(line: str, refusal: str, tmp_path: Path) -> None:
    path = tmp_path / "starpulse.toml"
    path.write_text(line + "\n")

    with pytest.raises(ValueError, match=refusal):
        load(path)
