"""A browser's side of an OpenID Connect sign-in against the mock issuer container (`issuer` fixture)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message

#: The mock issuer: its login form takes any username and a JSON `claims` field, so a test chooses the account's groups.
IMAGE = "ghcr.io/navikt/mock-oauth2-server:2.1.10"
Answer = tuple[int, dict[str, str], bytes]


class _Stay(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def _headers(raw: Message) -> dict[str, str]:
    """Lower-cased names; a header sent twice (`Set-Cookie`) is its values joined by newlines."""
    return {name.lower(): "\n".join(raw.get_all(name) or []) for name in set(raw.keys())}


def call(target: str, method: str = "GET", headers: dict[str, str] | None = None, data: bytes | None = None) -> Answer:
    """One request, answered without following a redirect: status, lower-cased headers, body."""
    request = urllib.request.Request(target, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.build_opener(_Stay).open(request, timeout=10) as resp:
            return resp.status, _headers(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, _headers(exc.headers), exc.read()


def answers(target: str) -> bool:
    """Whether `target` answers 200; a refused or reset connection is not yet."""
    try:
        return call(target)[0] == 200
    except OSError:  # a published port accepts before the server inside is up
        return False


def sign_in(base: str, issuer: str, username: str, groups: list[str]) -> Answer:
    """What the browser does at the hub on `base`: the sign-in start, the issuer's form, the callback; its answer."""
    status, headers, _ = call(f"{base}/auth/login")
    assert status == 302, "the sign-in start sends the browser to the issuer"
    cookie = headers["set-cookie"].partition(";")[0]
    assert headers["location"].startswith(issuer)
    form = urllib.parse.urlencode({"username": username, "claims": json.dumps({"groups": groups})}).encode()
    status, back, _ = call(headers["location"], "POST", {"Content-Type": "application/x-www-form-urlencoded"}, form)
    assert status == 302, "the issuer sends the browser back with a code"
    callback = urllib.parse.urlsplit(back["location"])
    return call(f"{base}{callback.path}?{callback.query}", headers={"Cookie": cookie})


def session_of(answer: Answer) -> str:
    """The session cookie a sign-in's answer sets, as a `Cookie` header value."""
    cookies = answer[1]["set-cookie"].split("\n")
    return next(c.partition(";")[0] for c in cookies if c.startswith("starpulse_session="))
