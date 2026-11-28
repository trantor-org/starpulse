"""The `[github]` config table: the intake listener `starpulse serve` runs, and what it accepts.

With the table, the `contexts` child listens for GitHub App webhook deliveries on `host:port` and saves each signed one
to the `github_inbox` table before it answers; without it no listener runs.

- `secret_env`: the name of the environment variable that holds the App's webhook secret (required; the secret itself
  never goes in the config).
- `organisation`, `repositories`: whose deliveries are saved, an owner and `owner/name` entries; at least one is required.
- `inbox_files`: a glob for the old inbox database files that `starpulse migrate` copies into the store once (default none); the
  inbox itself lives in the store the config's `database_url` names.
- `max_body_bytes`: the largest body accepted (default 5 MiB).
- `host`, `port`: where to bind (default `127.0.0.1:8767`; a container that publishes the port needs a wider host).
- `reconcile_token_env`: the name of the environment variable that holds a GitHub token able to read the App's deliveries
  and redeliver them, and to read the accepted repositories' pull requests and checks. With it, the sweeper's `github`
  kind reconciles the inbox against GitHub on each sweeper pass; without it, none runs.
"""

from dataclasses import dataclass

__all__ = ["GitHub", "GitHubConfigError", "parse_github"]

_KEYS = {"secret_env", "organisation", "repositories", "inbox_files", "max_body_bytes", "host", "port", "reconcile_token_env"}


class GitHubConfigError(ValueError):
    """The table cannot be read; the message names the key to fix."""


@dataclass(frozen=True)
class GitHub:
    secret_env: str
    organisation: str | None = None
    repositories: tuple[str, ...] = ()
    inbox_files: str | None = None
    max_body_bytes: int = 5 * 1024 * 1024
    host: str = "127.0.0.1"
    port: int = 8767
    reconcile_token_env: str | None = None

    def accepts(self, repository: str) -> bool:
        """Whether `repository` (`owner/name`) belongs to the organisation or is listed."""
        owner = repository.partition("/")[0]
        return repository in self.repositories or (self.organisation is not None and owner == self.organisation)


def _text(raw: dict[str, object], key: str) -> str | None:
    value = raw.get(key)
    if value is not None and (not isinstance(value, str) or not value):
        raise GitHubConfigError(f"github: {key} must be a non-empty string")
    return value


def _whole(raw: dict[str, object], key: str, default: int, upper: int | None = None) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or (upper is not None and value > upper):
        bound = f"1 to {upper}" if upper else "1 or more"
        raise GitHubConfigError(f"github: {key} must be a whole number from {bound}")
    return value


def parse_github(raw: object) -> GitHub:
    """The `[github]` table a config has; the caller passes none for a config without one. Each refusal names the key to fix."""
    if not isinstance(raw, dict):
        raise GitHubConfigError("github must be a [github] table")
    if unknown := sorted(raw.keys() - _KEYS):
        raise GitHubConfigError(f"github: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_KEYS))}")
    secret_env = _text(raw, "secret_env")
    if secret_env is None:
        raise GitHubConfigError("github: secret_env names the environment variable that holds the webhook secret")
    organisation = _text(raw, "organisation")
    listed = raw.get("repositories", [])
    if not isinstance(listed, list) or not all(isinstance(r, str) and r.count("/") == 1 and all(r.split("/")) for r in listed):
        raise GitHubConfigError("github: repositories must be a list of owner/name strings")
    if organisation is None and not listed:
        raise GitHubConfigError("github: name an organisation or repositories to accept")
    defaults = GitHub(secret_env)
    return GitHub(
        secret_env=secret_env,
        organisation=organisation,
        repositories=tuple(listed),
        inbox_files=_text(raw, "inbox_files"),
        max_body_bytes=_whole(raw, "max_body_bytes", defaults.max_body_bytes),
        host=_text(raw, "host") or defaults.host,
        port=_whole(raw, "port", defaults.port, 65535),
        reconcile_token_env=_text(raw, "reconcile_token_env"),
    )
