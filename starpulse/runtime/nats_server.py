"""The optional NATS bridge's server: the official `nats-server` release, checked and run by `serve` as its `nats` child.

`[bridge] enabled = true` makes `serve` supervise `python -m starpulse.runtime.nats_server`, which fetches the pinned
release's archive for this platform, checks it against the release's published `SHA256SUMS`, keeps the binary in the
user cache beside the digest it was verified as, and runs it on localhost only with JetStream on. A binary that no longer
matches that digest is refused, never fetched over. The child imports StarPulse only for the interpreter path and the
watch on `serve`'s pipe.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import platform
import signal
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starpulse.bridge.subscriptions import Rules

#: The release `serve` runs; a newer one is a change to this line.
VERSION = "v2.15.2"
DEFAULT_PORT = 4222
#: Where the store goes when `[bridge] store_dir` names none, beside the config like the history database.
DEFAULT_STORE = "starpulse-nats"
#: The `<board>` of the subjects the bridge publishes when `[bridge] board` names none.
DEFAULT_BOARD = "trantor"
#: The command that resumes an ended session when none is configured; the session id and the events follow it.
DEFAULT_RESUME = ("claude", "--bg", "--resume")
#: The child's name in `serve`'s children, which its log lines and the closure name it by.
CHILD = "nats"

_RELEASE = "https://github.com/nats-io/nats-server/releases/download/{version}/{name}"
_SYSTEMS = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}
_MACHINES = {"x86_64": "amd64", "AMD64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64", "ARM64": "arm64"}


class BridgeError(RuntimeError):
    """The server cannot be fetched, verified or placed; the child exits naming why."""


@dataclass(frozen=True)
class Bridge:
    """The `[bridge]` table: no table, no server."""

    enabled: bool = False
    port: int = DEFAULT_PORT
    store_dir: str | None = None
    board: str = DEFAULT_BOARD
    subscriptions: Mapping[str, Rules] = field(default_factory=dict)
    """The subjects a session of each task kind subscribes to, by event: `[bridge.subscriptions.<kind>]`."""
    resume: tuple[str, ...] = DEFAULT_RESUME
    """The command that resumes an ended session; the session id and the events follow it."""
    sessions_dir: str | None = None
    """Where session inboxes are registered, instead of beside the config: `[bridge] sessions_dir`."""


def asset_name(system: str, machine: str) -> str:
    """The release archive for `platform.system()` and `platform.machine()`."""
    os_name, arch = _SYSTEMS.get(system), _MACHINES.get(machine)
    if os_name is None or arch is None:
        raise BridgeError(f"nats-server {VERSION} has no release for {system} {machine}")
    return f"nats-server-{VERSION}-{os_name}-{arch}.{'zip' if os_name == 'windows' else 'tar.gz'}"


def cache_root(system: str | None = None) -> Path:
    """The user cache directory of `system`, where the verified binary is kept."""
    home = Path.home()
    match system or platform.system():
        case "Windows":
            return Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "starpulse"
        case "Darwin":
            return home / "Library" / "Caches" / "starpulse"
        case _:
            return Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache") / "starpulse"


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - a fixed https release URL
        return response.read()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _published(sums: bytes, name: str) -> str:
    for line in sums.decode().splitlines():
        digest, _, file = line.partition(" ")
        if file.strip().lstrip("*") == name:
            return digest
    raise BridgeError(f"nats-server {VERSION} publishes no checksum for {name}")


def _extract(archive: bytes, name: str) -> bytes:
    """The server binary inside the release archive `name`."""
    binary = "nats-server.exe" if name.endswith(".zip") else "nats-server"
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            member = next(m for m in zipped.namelist() if m.rsplit("/", 1)[-1] == binary)
            return zipped.read(member)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tarred:
        member = next(m for m in tarred.getmembers() if m.isfile() and m.name.rsplit("/", 1)[-1] == binary)
        return tarred.extractfile(member).read()  # type: ignore[union-attr]


def ensure_binary(
    *,
    fetch: Callable[[str], bytes] | None = None,
    cache: Path | None = None,
    system: str | None = None,
    machine: str | None = None,
) -> Path:
    """The verified `nats-server` binary: the cached one when it still matches the digest it was verified as, else the
    release's, fetched and checked against its published checksum. A mismatch raises `BridgeError`; nothing is kept."""
    fetch = fetch or _download
    system = system or platform.system()
    name = asset_name(system, machine or platform.machine())
    folder = (cache or cache_root(system)) / "nats-server" / VERSION
    binary = folder / ("nats-server.exe" if system == "Windows" else "nats-server")
    sidecar = binary.with_name(binary.name + ".sha256")
    if binary.exists() and sidecar.exists():
        actual, verified = _sha256(binary.read_bytes()), sidecar.read_text().strip()
        if actual != verified:
            raise BridgeError(f"{binary}: sha256 {actual} is not the {verified} it was verified as")
        return binary
    archive = fetch(_RELEASE.format(version=VERSION, name=name))
    published = _published(fetch(_RELEASE.format(version=VERSION, name="SHA256SUMS")), name)
    if (actual := _sha256(archive)) != published:
        raise BridgeError(f"{name}: sha256 {actual} is not the published {published}")
    content = _extract(archive, name)
    folder.mkdir(parents=True, exist_ok=True)
    partial = binary.with_name(binary.name + ".partial")
    partial.write_bytes(content)
    partial.chmod(0o755)
    partial.replace(binary)
    sidecar.write_text(_sha256(content) + "\n")
    return binary


def server_command(binary: Path, port: int, store_dir: Path) -> list[str]:
    """`nats-server` on localhost only, JetStream on, its store in `store_dir`."""
    return [str(binary), "-a", "127.0.0.1", "-p", str(port), "-js", "-sd", str(store_dir)]


def bridge_commands(config: object, config_path: Path | None) -> dict[str, list[str]]:
    """The `nats` child `serve` supervises when `config` switches the bridge on, else none."""
    bridge: Bridge = config.bridge  # type: ignore[attr-defined]
    if not bridge.enabled:
        return {}
    base = config_path.parent if config_path else Path.cwd()
    store = Path(bridge.store_dir) if bridge.store_dir else base / DEFAULT_STORE
    from starpulse.runtime import launch  # noqa: PLC0415 - the child itself imports nothing of StarPulse

    return {CHILD: [launch.interpreter(), "-m", __name__, "--port", str(bridge.port), "--store-dir", str(store)]}


def _die_with_parent() -> None:  # pragma: no cover - runs in the forked child
    """Linux: the server gets `SIGTERM` when this launcher dies, even by `SIGKILL`, so none outlives it holding the port."""
    if sys.platform == "linux":
        import ctypes  # noqa: PLC0415

        ctypes.CDLL(None).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="nats_server", description="Run the verified nats-server for `serve`.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--store-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        binary = ensure_binary()
    except (BridgeError, OSError) as exc:
        parser.exit(1, f"nats-server not started: {exc}\n")
    args.store_dir.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        server_command(binary, args.port, args.store_dir),
        stdin=subprocess.DEVNULL,
        preexec_fn=_die_with_parent if sys.platform == "linux" else None,  # noqa: PLW1509
    )
    from starpulse.runtime.hold import watch_supervisor  # noqa: PLC0415 - ends this process when `serve` dies

    signal.signal(signal.SIGTERM, lambda *_: process.terminate())
    watch_supervisor()
    sys.exit(process.wait() or 0)


if __name__ == "__main__":
    main()
