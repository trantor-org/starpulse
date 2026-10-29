"""Share the servers of `test_agent_cli.py` between its cases: a module run builds each once, not once per case.

The module declares each server as a function-scoped fixture, so each of its 387 cases built and stopped the servers it
named. At collection, before pytest reads the module's fixtures, this plugin swaps every server fixture (the module's
`SERVERS`) and its `writer` for a module-scoped one that runs the same builder once in a directory of its own.

A case must still meet the server it would have built for itself. The shared server watches its requests: after a case
sent anything but a GET through it, the plugin stops it, empties its directory and
builds it again on the same port, so its URL holds. Under `-n` all the module's cases run on one worker (a worker that
took some would build every server again). A case that names a shared server also gets that server's directory as `tmp_path`, where the files it
inspects are. The `writer` is emptied after every case.
"""

from __future__ import annotations

import inspect
import shutil
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import pytest
from starpulse.views.adapters.inbound.gate_request import GateRequest

MODULES = ("test_agent_cli.py",)
_HOSTING: ContextVar[Any] = ContextVar("hosting", default=None)  # the `_Hosted` being built, for the kit's `serve`


class _Hosted:
    """One shared server: built when first asked for, built again, on its port and in its directory, after a write."""

    def __init__(self, root: Path, original: Callable[..., Any], shared: dict[str, Any]) -> None:
        self.root = root
        self.build = contextmanager(original)
        self.params = tuple(inspect.signature(original).parameters)
        self.shared = shared
        self.port = 0
        self.url = ""
        self.wrote = False
        self.stack = ExitStack()

    @property
    def rooted(self) -> bool:
        return "tmp_path" in self.params

    def gate(self, request: GateRequest) -> bool:
        """Admit every request; note one that is not a read, whatever the server answers."""
        if request.command != "GET":
            self.wrote = True
        return True

    def start(self) -> None:
        self.wrote = False
        self.stack = ExitStack()
        patch = self.stack.enter_context(pytest.MonkeyPatch.context())
        given = {"tmp_path": self.root, "monkeypatch": patch, **self.shared}
        token = _HOSTING.set(self)
        try:
            self.url = self.stack.enter_context(self.build(**{name: given[name] for name in self.params}))
        finally:
            _HOSTING.reset(token)

    def renew(self) -> None:
        if not self.wrote:
            return
        self.stack.close()
        shutil.rmtree(self.root)
        self.root.mkdir()
        self.start()


class _Hosts:
    """The `_Hosted` servers of one module run, by fixture name."""

    def __init__(self, factory: pytest.TempPathFactory) -> None:
        self.factory = factory
        self.by_name: dict[str, _Hosted] = {}

    def url(self, name: str, original: Callable[..., Any], shared: dict[str, Any]) -> str:
        if name not in self.by_name:
            host = self.by_name[name] = _Hosted(self.factory.mktemp(name), original, shared)
            host.start()
        return self.by_name[name].url

    def renew(self) -> None:
        for host in self.by_name.values():
            host.renew()

    def close(self) -> None:
        for host in self.by_name.values():
            host.stack.close()


def _wrapped(fixture: Any) -> Callable[..., Any]:
    """The function a fixture definition decorates."""
    return fixture.__wrapped__


def _server(name: str, original: Callable[..., Any]) -> Any:
    """The module-scoped fixture of one server: it runs the module's builder once per module run."""
    extras = [param for param in inspect.signature(original).parameters if param not in ("tmp_path", "monkeypatch")]

    @pytest.fixture(scope="module", name=name)
    def server(request: pytest.FixtureRequest, hosts: _Hosts) -> str:
        shared = {param: request.getfixturevalue(param) for param in extras}
        return hosts.url(name, original, shared)

    return server


def _writer(original: Callable[..., Any]) -> Any:
    """The module's `writer`, built once; `fresh_servers` empties it after each case."""

    @pytest.fixture(scope="module", name="writer")
    def writer() -> Any:
        return original()

    return writer


def share(module: Any) -> None:
    """Replace the module's server fixtures, its `writer`, and `tmp_path` and the autouse reset that go with them."""
    if hasattr(module, "fresh_servers"):
        return
    names = set(module.SERVERS.values())
    for name in names:
        setattr(module, name, _server(name, _wrapped(getattr(module, name))))
    module.writer = _writer(_wrapped(module.writer))
    real = module._real_serve

    @contextmanager
    def serve(*args: Any, **kwargs: Any) -> Iterator[Any]:
        """The kit's `serve`; under a `_Hosted` build it takes the host's port and tells the host when a request writes."""
        host = _HOSTING.get()
        if host:
            kwargs.update(port=host.port, gate=host.gate)
        with real(*args, **kwargs) as server:
            if host:
                host.port = server.server_port
            yield server

    module._real_serve = serve

    @pytest.fixture(scope="module", name="hosts")
    def hosts(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Hosts]:
        shared = _Hosts(tmp_path_factory)
        yield shared
        shared.close()

    @pytest.fixture(autouse=True, name="fresh_servers")
    def fresh_servers(hosts: _Hosts, writer: Any) -> Iterator[None]:
        """After each case, the shared servers it wrote through and the writer it asked are as new."""
        yield
        hosts.renew()
        vars(writer).update(vars(type(writer)()))

    @pytest.fixture(name="tmp_path")
    def tmp_path(request: pytest.FixtureRequest, tmp_path: Path, hosts: _Hosts) -> Path:
        """A case that names a shared server gets that server's directory, where the files it inspects are."""
        for name in sorted(names & set(request.fixturenames)):
            request.getfixturevalue(name)
            host = hosts.by_name[name]
            if host.rooted:
                return host.root
        return tmp_path

    module.hosts, module.fresh_servers, module.tmp_path = hosts, fresh_servers, tmp_path


@pytest.hookimpl(tryfirst=True)
def pytest_xdist_make_scheduler(config: pytest.Config, log: Any) -> Any:
    """Under `-n`, send all of a shared module's cases to one worker: each worker that took some would build every
    server again, and that is most of the module's cost. Every other test is scheduled as `--dist load` does."""
    if config.getoption("dist", None) != "load":
        return None
    from xdist.scheduler import LoadScopeScheduling

    class Scheduling(LoadScopeScheduling):
        def _split_scope(self, nodeid: str) -> str:
            path = nodeid.split("::")[0]
            return path if path.rsplit("/", 1)[-1] in MODULES else nodeid

    return Scheduling(config, log)


def pytest_collectstart(collector: pytest.Collector) -> None:
    if isinstance(collector, pytest.Module) and collector.path.name in MODULES:
        share(collector.obj)
