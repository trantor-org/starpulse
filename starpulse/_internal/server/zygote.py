"""The preloaded process `serve` forks its worker children from, so they share the pages of what every worker imports.

`serve` starts one process (`python -m starpulse._internal.server.zygote`) that imports the modules every supervised context
runs from, freezes them out of the garbage collector's way and then waits on a socket from `serve`. For each worker `serve`
asks it to start, it forks: the child runs the same `starpulse worker <context>` main a `subprocess` child would, but its
interpreter and imports are the preloaded process's own pages until it writes to them, so a context keeps its own process
(restart, reload, memory limit) and the import floor is paid once. The pages a child shares are why the memory a worker is
judged on is its proportional size (`starpulse._internal.server.memory`).

`Forker` is the `spawn` the `Supervisor` takes. A reload that changes a module the preloaded process imported retires it: it
takes no more forks and exits when its last child has, and the next fork asks a new one that has the new code. Where the
platform has no safe `fork` (everywhere but Linux), or the preloaded process fails, children start with `subprocess` as
`spawn_child` does, as does a child handed a listening socket (the Page API's), which it inherits from `serve` itself.
"""

from __future__ import annotations

import gc
import importlib
import json
import logging
import os
import select
import signal
import socket
import subprocess
import sys
import time
import traceback
from collections.abc import Callable, Sequence
from typing import IO, Any, NoReturn

from starpulse._internal.server.hold import LISTEN_FD_ENV, SUPERVISED_ENV, watch_supervisor
from starpulse._internal.server.supervisor import spawn_child

logger = logging.getLogger(__name__)

#: What a forked child runs: the module and function `starpulse worker <context>` goes through.
ENTRY = "starpulse.__main__:main"

#: A worker command `worker_commands` builds starts with these; the rest is the argument line the entry takes.
_PREFIX = [sys.executable, "-m", "starpulse"]

_ANSWER_S = 60.0  # how long the preloaded process may take to import and answer
_REAP_S = 0.1


def fork_supported() -> bool:
    """Whether this platform forks children from a preloaded process: Linux, where a single-threaded `fork` is safe."""
    return sys.platform.startswith("linux")


# The preloaded process


def _exit_code(value: object) -> int:
    """The status an interpreter would exit with for `SystemExit(value)`."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    print(value, file=sys.stderr)
    return 1


def _child(
    control: socket.socket, run: Callable[[list[str]], Any], argv: list[str], env: dict[str, str]
) -> NoReturn:  # pragma: no mutate block — process boundary
    """What a fork becomes: the worker `run` with `argv` and `env` added, then the process ends with its status."""
    control.close()
    os.environ.update(env)
    sys.argv = ["starpulse", *argv]
    watch_supervisor()
    try:
        code = _exit_code(run(argv))
    except SystemExit as exit_:
        code = _exit_code(exit_.code)
    except BaseException:
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    logging.shutdown()
    os._exit(code)


def _reap(exits: dict[int, int]) -> None:
    """Collect every child that ended, keeping its exit code for `serve` to ask for."""
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if not pid:
            return
        exits[pid] = os.waitstatus_to_exitcode(status)


def _serve(
    control: socket.socket, run: Callable[[list[str]], Any]
) -> None:  # pragma: no mutate block — process boundary
    """Answer `serve` one request at a time until it closes the socket, or until it retired this process and the last
    child is gone. Single-threaded, so a `fork` copies no other thread's locks."""
    requests = control.makefile("rb")
    children: set[int] = set()
    exits: dict[int, int] = {}
    retired = False
    while True:
        _reap(exits)
        children -= exits.keys()
        if retired and not children:
            return
        if not select.select([control], [], [], _REAP_S)[0]:
            continue
        line = requests.readline()
        if not line:
            return
        request = json.loads(line)
        if request["op"] == "fork":
            pid = os.fork()
            if not pid:
                requests.close()
                _child(control, run, request["argv"], request.get("env", {}))
            children.add(pid)
            reply: dict[str, Any] = {"pid": pid}
        elif request["op"] == "exit":
            reply = {"code": exits.pop(request["pid"], None)}
        else:
            retired = True
            reply = {}
        control.sendall(json.dumps(reply).encode() + b"\n")


def _preload(control: socket.socket, entry: str, modules: Sequence[str]) -> None:  # pragma: no mutate block — process boundary
    """Import `modules` and `entry`'s module, then answer `control`."""
    gc.disable()  # the imports build a graph that lives to exit; collecting during them is time the first fork waits on
    for module in modules:
        importlib.import_module(module)
    name, _, function = entry.partition(":")
    run = getattr(importlib.import_module(name), function)
    gc.collect()
    gc.freeze()
    gc.enable()
    _serve(control, run)


def main(argv: list[str]) -> None:  # pragma: no mutate block — process boundary
    """`argv` is the control socket's descriptor, the entry (`module:function`) and the modules to preload."""
    fd, entry, *modules = argv
    logging.basicConfig(level=logging.INFO)
    _preload(socket.socket(fileno=int(fd)), entry, modules)


# `serve`'s side


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class _Forked:
    """A child of the preloaded process, shaped like the `Popen` the `Supervisor` drives.

    It is not `serve`'s child, so it is alive while its pid is and its exit code is what the preloaded process reaped."""

    def __init__(self, pid: int, preloaded: _Preloaded) -> None:
        self.pid = pid
        self._preloaded = preloaded
        self._code: int | None = None

    def poll(self) -> int | None:
        if self._code is None and not _running(self.pid):
            self._code = self._preloaded.exit_code(self.pid)
        return self._code

    def send_signal(self, number: int) -> None:
        try:
            os.kill(self.pid, number)
        except ProcessLookupError:
            pass

    def terminate(self) -> None:
        self.send_signal(signal.SIGTERM)

    def kill(self) -> None:
        self.send_signal(signal.SIGKILL)

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while (code := self.poll()) is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(str(self.pid), timeout)
            time.sleep(0.01)
        return code


class _Forkproc(_Forked):
    """A preloaded process `serve` forked itself, shaped like the `Popen` the other kind is."""

    def __init__(self, pid: int, stdin: IO[bytes]) -> None:
        self.pid = pid
        self.stdin = stdin
        self._status: int | None = None

    def poll(self) -> int | None:
        if self._status is None:
            done, status = os.waitpid(self.pid, os.WNOHANG)
            if done:
                self._status = os.waitstatus_to_exitcode(status)
        return self._status

    def send_signal(self, sig: int) -> None:
        if self._status is None:
            os.kill(self.pid, sig)


def _fork_preloaded(ours: socket.socket, theirs: socket.socket, entry: str, modules: Sequence[str]) -> _Forkproc:
    """Fork the preloaded process from `serve` before it has threads: it starts with `serve`'s imports already loaded."""
    reader, writer = os.pipe()
    pid = os.fork()
    if pid:
        os.close(reader)
        return _Forkproc(pid, os.fdopen(writer, "wb"))
    try:  # pragma: no mutate block — process boundary
        os.setsid()
        os.dup2(reader, 0)
        os.close(reader)
        os.close(writer)
        ours.close()
        os.environ[SUPERVISED_ENV] = "1"
        _preload(theirs, entry, modules)
    except BaseException:
        traceback.print_exc()
        os._exit(1)
    os._exit(0)


class _Preloaded:
    """One preloaded process and the socket `serve` asks it over."""

    def __init__(
        self, modules: Sequence[str], entry: str, inherited: Sequence[int] = (), *, forked: bool = False
    ) -> None:
        ours, theirs = socket.socketpair()
        if forked:
            self.proc = _fork_preloaded(ours, theirs, entry, modules)
        else:
            # its stdin pipe from `serve` is the one every fork inherits, so a child still ends when `serve` dies
            self.proc = subprocess.Popen(
                [sys.executable, "-m", __name__, str(theirs.fileno()), entry, *modules],
                stdin=subprocess.PIPE,
                env={**os.environ, SUPERVISED_ENV: "1"},
                start_new_session=True,
                pass_fds=[theirs.fileno(), *inherited],
            )
        theirs.close()
        ours.settimeout(_ANSWER_S)
        self._control = ours
        self._answers = ours.makefile("rb")

    def ask(self, request: dict[str, Any]) -> dict[str, Any]:
        self._control.sendall(json.dumps(request).encode() + b"\n")
        line = self._answers.readline()
        if not line:
            raise ConnectionError("the preloaded process closed its socket")
        return json.loads(line)

    def fork(self, argv: Sequence[str], env: dict[str, str]) -> _Forked:
        return _Forked(self.ask({"op": "fork", "argv": list(argv), "env": env})["pid"], self)

    def exit_code(self, pid: int) -> int:
        """The code the preloaded process reaped `pid` with; -1 when it is gone and took the code with it."""
        try:
            code = self.ask({"op": "exit", "pid": pid})["code"]
        except OSError, ValueError:
            return -1
        return -1 if code is None else code

    def retire(self) -> None:
        """Take no more forks; the process exits when its last child has."""
        try:
            self.ask({"op": "retire"})
        except OSError, ValueError:
            pass  # it is already gone, and its children run on without it

    def close(self) -> None:
        """End the process: it exits at the closed socket, and closing its stdin pipe stops any child it still has."""
        self._answers.close()
        self._control.close()
        self.proc.stdin.close()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


class Forker:
    """The `Supervisor`'s `spawn`: forks a worker command's child from a preloaded process, else starts it with `fallback`.

    The `Supervisor` calls it, `retire` and nothing else under its lock, so it takes none of its own. `modules` are what
    the preloaded process imports and `entry` is the function a child runs with the command's arguments. `listening`
    is the socket `serve` hands the Page API: the preloaded process inherits it, so that child forks like the others."""

    def __init__(
        self,
        modules: Sequence[str],
        entry: str = ENTRY,
        fallback: Callable[..., Any] = spawn_child,
        listening: socket.socket | None = None,
    ) -> None:
        self._listening = listening
        self._modules = list(modules)
        self._entry = entry
        self._fallback = fallback
        self._current: _Preloaded | None = None
        self._retired: list[_Preloaded] = []
        self._failed = not fork_supported()

    def start(self, *, forked: bool = False) -> None:
        """Start the preloaded process now, so its imports overlap the rest of `serve`'s start.

        `forked` forks it from this process, which has not started a thread, so it begins with what `serve` imported."""
        if self._current is None and not self._failed:
            try:
                self._current = _Preloaded(self._modules, self._entry, self._inherited(), forked=forked)
            except OSError as exc:
                self._fail(exc)

    def _inherited(self) -> list[int]:
        if self._listening is None:
            return []
        self._listening.set_inheritable(True)
        return [self._listening.fileno()]

    def __call__(self, command: Sequence[str], listening: socket.socket | None = None, ready: int | None = None) -> Any:
        handed = () if listening is None else (listening,)  # every start but a fork must still pass the socket on
        if ready is not None:  # the preloaded process cannot inherit a descriptor made after it started
            return self._fallback(command, listening, ready)
        if (
            listening is not None and listening is not self._listening
        ):  # a fork inherits only what the preloaded process holds
            return self._fallback(command, *handed)
        if list(command[: len(_PREFIX)]) != _PREFIX:
            return self._fallback(command, *handed)
        self.start()
        if self._current is not None:
            try:
                env = {} if listening is None else {LISTEN_FD_ENV: str(listening.fileno())}
                return self._current.fork(command[len(_PREFIX) :], env)
            except (OSError, ValueError, KeyError) as exc:
                self._fail(exc)
        return self._fallback(command, *handed)

    def _fail(self, exc: Exception) -> None:
        logger.warning("the preloaded process failed (%s); workers start with subprocess from now on", exc)
        self._failed = True
        if self._current is not None:
            self._current.close()
            self._current = None

    def retire(self) -> None:
        """Stop forking from the current preloaded process and start one that imports the code now installed."""
        self._retired = [old for old in self._retired if old.proc.poll() is None]
        if self._current is not None:
            self._current.retire()
            self._retired.append(self._current)
            self._current = None
        self.start()

    def close(self) -> None:
        for preloaded in (self._current, *self._retired):
            if preloaded is not None:
                preloaded.close()
        self._current = None
        self._retired = []


if __name__ == "__main__":
    main(sys.argv[1:])
