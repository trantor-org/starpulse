"""A child the supervisor starts for a socket inherits it on the descriptor its environment names."""

import socket
import sys
from pathlib import Path

from starpulse.runtime.hold import LISTEN_FD_ENV
from starpulse.runtime.supervisor import spawn_child


def test_a_child_is_handed_the_listening_socket_on_the_descriptor_its_environment_names(tmp_path: Path) -> None:
    seen = tmp_path / "port"
    adopt = (
        "import os, socket, sys; s = socket.socket(fileno=int(os.environ['" + LISTEN_FD_ENV + "'])); "
        "open(sys.argv[1], 'w').write(str(s.getsockname()[1]))"
    )
    with socket.create_server(("127.0.0.1", 0)) as listening:
        child = spawn_child([sys.executable, "-c", adopt, str(seen)], listening)
        assert child.wait(20) == 0
        assert seen.read_text() == str(listening.getsockname()[1])
