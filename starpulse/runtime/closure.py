"""Whether a `starpulse.toml` change needs `serve` itself restarted, for the apply-on-merge router.

A `starpulse reload` replaces every child and re-executes `serve`, so it reads no code and no config to decide what to
replace. It cannot move what `serve` holds across a re-exec: the listening socket and its certificate, and the sockets it
binds for the contexts child. A change to one of those needs the service restarted, which `restarts_serve` says.
"""

from collections.abc import Mapping

from starpulse.runtime.config import _KEYS

#: The keys `serve` alone reads: each child's memory limit, its refresh token and its take-over command,
#: and the certificate it wraps the shared listening socket in, which a hot swap behind that socket cannot change.
_SERVE_KEYS = frozenset(
    {
        "host",
        "port",
        "hours",
        "tls_cert",
        "tls_key",
        "mode",
        "github_token_env",
        "take_over_command",
        "webhook_producer",
        "webhook_token_env",
        "worker_memory",
        "bridge",
    }
)

#: The tables whose `host` and `port` `serve` binds the contexts child's held sockets to: a replacement child is handed
#: the held socket, so a new address needs `serve` itself restarted, which binds it.
_BOUND_TABLES = ("github", "claude_code")


def _address(raw: Mapping[str, object], table: str) -> tuple[object, object]:
    held = raw.get(table)
    return (held.get("host"), held.get("port")) if isinstance(held, Mapping) else (None, None)


def restarts_serve(old: Mapping[str, object], new: Mapping[str, object]) -> bool:
    """Whether a change from the `old` to the `new` raw `starpulse.toml` needs `serve` itself restarted.

    True when a changed key is one only `serve` reads or one the config does not name, or a table `serve` holds a socket
    for names another host or port. Any other change is applied by the reload's replacing every child."""
    changed = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    moved = any(_address(old, table) != _address(new, table) for table in _BOUND_TABLES)
    return moved or any(key in _SERVE_KEYS or key not in _KEYS for key in changed)


class ReloadError(RuntimeError):
    """A reload could not replace every child; the children it did not end keep running."""
