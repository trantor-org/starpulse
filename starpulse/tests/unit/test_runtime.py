"""Where the view's Redis comes from: REDIS_URL, a named Valkey container, or a refusal that names REDIS_URL."""

import subprocess

import pytest

from starpulse import runtime
from starpulse.runtime import CONTAINER, IMAGE, RedisUnavailableError, ensure_redis

#: The streams the view reads itself, and one a board adapter names.
PREFIXES = ("MACHINE_EVENTS", "RUNS", "BOARD")


class Runtime:
    """A stand-in for the docker or podman CLI: records each call and answers from a canned container."""

    def __init__(self, exists: bool = False, running: bool = False, published: str = "127.0.0.1:49153") -> None:
        self.exists, self.running, self.published = exists, running, published
        self.calls: list[tuple[str, ...]] = []
        self.options: list[dict[str, object]] = []

    def __call__(self, argv: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(tuple(argv))
        self.options.append(options)
        verb = argv[1]
        if verb == "inspect":
            ok = self.exists
            return subprocess.CompletedProcess(argv, 0 if ok else 1, "true\n" if self.running else "false\n", "")
        if verb == "port":
            return subprocess.CompletedProcess(argv, 0, f"{self.published}\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def verbs(self) -> list[str]:
        return [c[1] for c in self.calls]


def _ensure(environ: dict[str, str], runtime: Runtime, binaries: tuple[str, ...] = ("docker",), **kw) -> None:
    ensure_redis(
        environ,
        which=lambda name: f"/usr/bin/{name}" if name in binaries else None,
        run=runtime,
        ping=lambda host, port: True,
        **kw,
    )


def test_redis_url_points_every_stream_and_the_board_adapters_at_it_and_starts_nothing() -> None:
    environ = {"REDIS_URL": "redis://:s3cret@redis-host:6390/0"}
    runtime = Runtime()

    _ensure(environ, runtime, prefixes=("BOARD",))

    assert runtime.calls == []
    assert {p: (environ[f"{p}_REDIS_HOST"], environ[f"{p}_REDIS_PORT"]) for p in PREFIXES} == dict.fromkeys(
        PREFIXES, ("redis-host", "6390")
    )
    assert environ["REDIS_PASSWORD"] == "s3cret"


def test_a_url_user_and_encoded_password_are_exported_decoded() -> None:
    environ = {"REDIS_URL": "redis://worker:p%40ss@redis-host"}

    _ensure(environ, Runtime())

    assert (environ["REDIS_USERNAME"], environ["REDIS_PASSWORD"]) == ("worker", "p@ss")


def test_a_rediss_url_turns_tls_on_for_every_stream() -> None:
    environ = {"REDIS_URL": "rediss://redis-host:6390"}

    _ensure(environ, Runtime())

    assert environ["REDIS_SSL"] == "1"


def test_a_url_without_a_port_or_password_leaves_the_password_alone() -> None:
    environ = {"REDIS_URL": "redis://redis.example.test", "REDIS_PASSWORD": "from-env"}

    _ensure(environ, Runtime())

    assert environ["MACHINE_EVENTS_REDIS_PORT"] == "6379"
    assert environ["REDIS_PASSWORD"] == "from-env"


def test_with_no_url_and_no_runtime_it_refuses_naming_redis_url() -> None:
    with pytest.raises(RedisUnavailableError, match="REDIS_URL"):
        _ensure({}, Runtime(), binaries=())


def test_the_first_run_creates_a_named_container_with_a_volume_and_points_the_streams_at_it() -> None:
    environ: dict[str, str] = {}
    runtime = Runtime(exists=False)

    _ensure(environ, runtime, prefixes=("BOARD",))

    created = next(c for c in runtime.calls if c[1] == "run")
    assert created[:5] == ("docker", "run", "-d", "--name", CONTAINER)
    assert f"{CONTAINER}:/data" in created
    assert "127.0.0.1::6379" in created
    assert environ["REDIS_URL"] == "redis://127.0.0.1:49153"
    assert environ["MACHINE_EVENTS_REDIS_PORT"] == environ["BOARD_REDIS_PORT"] == "49153"


def test_a_stopped_container_is_started_not_recreated() -> None:
    runtime = Runtime(exists=True, running=False)

    _ensure({}, runtime)

    assert "start" in runtime.verbs()
    assert "run" not in runtime.verbs()


def test_a_running_container_is_reused_untouched() -> None:
    runtime = Runtime(exists=True, running=True)

    _ensure({}, runtime)

    assert {"start", "run"}.isdisjoint(runtime.verbs())


def test_podman_is_used_when_docker_is_absent() -> None:
    runtime = Runtime()

    _ensure({}, runtime, binaries=("podman",))

    assert {call[0] for call in runtime.calls} == {"podman"}


def test_a_runtime_that_cannot_start_the_container_refuses_naming_redis_url() -> None:
    def failing(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "Cannot connect to the Docker daemon")

    with pytest.raises(RedisUnavailableError, match=r"Docker daemon.*REDIS_URL"):
        ensure_redis({}, which=lambda name: name, run=failing, ping=lambda host, port: True)


def test_a_container_that_never_answers_refuses_naming_redis_url() -> None:
    with pytest.raises(RedisUnavailableError, match="REDIS_URL"):
        ensure_redis({}, which=lambda name: name, run=Runtime(), ping=lambda host, port: False, ready_timeout=0.0)


HINT = "; set REDIS_URL to a Redis or Valkey server (redis://host:6379)"


def _refusal(environ: dict[str, str], **kw) -> str:
    with pytest.raises(RedisUnavailableError) as refused:
        _ensure(environ, kw.pop("runtime", Runtime()), **kw)
    return str(refused.value)


def test_no_runtime_refusal_says_what_is_missing_and_what_to_set() -> None:
    assert _refusal({}, binaries=()) == f"REDIS_URL is unset and neither docker nor podman is installed{HINT}"


def test_docker_is_preferred_over_podman_when_both_are_installed() -> None:
    runtime = Runtime()

    _ensure({}, runtime, binaries=("podman", "docker"))

    assert {call[0] for call in runtime.calls} == {"docker"}


def test_the_first_run_issues_exactly_these_commands_as_text_without_raising() -> None:
    runtime = Runtime(exists=False)

    _ensure({}, runtime)

    assert runtime.calls == [
        ("docker", "inspect", "-f", "{{.State.Running}}", CONTAINER),
        (
            "docker", "run", "-d", "--name", CONTAINER, "-v", f"{CONTAINER}:/data", "-p", "127.0.0.1::6379", IMAGE,
            "valkey-server", "--appendonly", "yes",
        ),
        ("docker", "port", CONTAINER, "6379/tcp"),
    ]  # fmt: skip
    assert all(o == {"capture_output": True, "text": True, "check": False, "timeout": 120} for o in runtime.options)


def test_a_stopped_container_is_started_by_name() -> None:
    runtime = Runtime(exists=True, running=False)

    _ensure({}, runtime)

    assert ("docker", "start", CONTAINER) in runtime.calls


def test_the_published_address_is_the_first_line_with_a_wildcard_host_made_loopback() -> None:
    environ: dict[str, str] = {}

    _ensure(environ, Runtime(exists=True, running=True, published="0.0.0.0:49200\n[::]:49201"))

    assert environ["REDIS_URL"] == "redis://127.0.0.1:49200"


def test_the_readiness_probe_gets_the_host_and_integer_port_and_is_retried() -> None:
    answers = iter([False, False, True])
    probes: list[tuple[str, int]] = []

    def ping(host: str, port: int) -> bool:
        probes.append((host, port))
        return next(answers)

    ensure_redis({}, which=lambda name: name, run=Runtime(), ping=ping)

    assert probes == [("127.0.0.1", 49153)] * 3


def test_a_container_that_never_answers_refuses_with_its_address_and_timeout() -> None:
    environ: dict[str, str] = {}

    with pytest.raises(RedisUnavailableError) as refused:
        ensure_redis(environ, which=lambda name: name, run=Runtime(), ping=lambda h, p: False, ready_timeout=0.0)

    assert str(refused.value) == f"{CONTAINER} did not answer on 127.0.0.1:49153 within 0 s{HINT}"
    assert "REDIS_URL" not in environ


class _Clock:
    """A clock whose sleep advances it, so a wait is measured without taking the time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_the_container_gets_twenty_seconds_to_answer_by_default_polled_every_fifth_of_a_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(runtime, "time", clock)

    with pytest.raises(RedisUnavailableError) as refused:
        ensure_redis({}, which=lambda name: name, run=Runtime(), ping=lambda h, p: False)

    assert str(refused.value) == f"{CONTAINER} did not answer on 127.0.0.1:49153 within 20 s{HINT}"
    assert set(clock.slept) == {0.2}
    assert 20.0 <= clock.now < 20.2 + 1e-9


def test_a_zero_timeout_gives_up_without_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    monkeypatch.setattr(runtime, "time", clock)

    with pytest.raises(RedisUnavailableError):
        ensure_redis({}, which=lambda name: name, run=Runtime(), ping=lambda h, p: False, ready_timeout=0.0)

    assert clock.slept == []


def test_a_runtime_failure_refusal_names_the_runtime_and_its_stderr() -> None:
    def failing(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", " no daemon \n")

    with pytest.raises(RedisUnavailableError) as refused:
        ensure_redis({}, which=lambda name: name, run=failing, ping=lambda h, p: True)

    assert str(refused.value) == f"docker could not start {CONTAINER}: no daemon{HINT}"


def test_a_url_with_no_host_defaults_to_loopback() -> None:
    environ = {"REDIS_URL": "redis://:6390"}

    _ensure(environ, Runtime())

    assert environ["MACHINE_EVENTS_REDIS_HOST"] == "127.0.0.1"


def test_an_address_whose_host_holds_colons_splits_at_the_last_one() -> None:
    probes: list[tuple[str, int]] = []

    def ping(host: str, port: int) -> bool:
        probes.append((host, port))
        return True

    ensure_redis(
        {}, which=lambda name: name, run=Runtime(exists=True, running=True, published="[::1]:49153"), ping=ping
    )

    assert probes == [("[::1]", 49153)]


def test_a_runtime_command_that_hangs_refuses_naming_redis_url() -> None:
    def hanging(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, 120)

    with pytest.raises(RedisUnavailableError, match=r"docker inspect timed out after 120 s.*REDIS_URL"):
        ensure_redis({}, which=lambda name: name, run=hanging, ping=lambda host, port: True)


@pytest.mark.parametrize("published", ["", "\n"], ids=["no-output", "blank-line"])
def test_a_container_that_publishes_no_port_refuses_naming_redis_url(published: str) -> None:
    runtime = Runtime(exists=True, running=True, published=published)

    with pytest.raises(RedisUnavailableError, match=r"publishes no port.*REDIS_URL"):
        _ensure({}, runtime)


def test_a_port_lookup_that_fails_refuses_with_the_runtimes_error() -> None:
    def failing_port(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if argv[1] == "port":
            return subprocess.CompletedProcess(argv, 1, "", "no public port")
        return subprocess.CompletedProcess(argv, 0, "true\n", "")

    with pytest.raises(RedisUnavailableError, match=r"no public port.*REDIS_URL"):
        ensure_redis({}, which=lambda name: name, run=failing_port, ping=lambda host, port: True)
