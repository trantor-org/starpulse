"""The hub's sign-in: viewers authenticate with the hub's OpenID Connect issuer before any route answers them.

This module and what it imports (PyJWT) are hub extras (`pip install 'starpulse[hub]'`). Only `serve --hub` imports it,
so an IC instance runs without them. `Gate` is the callable the server's handler asks before it routes a request:

- Every path is a viewer route unless `ROUTES` names it. A viewer route needs a session cookie from a completed sign-in
  and answers 401 without one, so a route added to the server is gated until someone decides otherwise.
- `/auth/login` and `/auth/callback` are the sign-in itself, open to anyone. The callback exchanges the code (with PKCE,
  a state held in a cookie, and a nonce), verifies the ID token's signature, issuer, audience, expiry and nonce, and
  refuses an account whose groups claim holds none of `allowed_groups`, saying so on the page. A refused account gets no
  session.
- An instance route (`/api/runs/events`) is open to the gate and checks its own per-instance bearer token. An engine
  route needs the engine token. Neither token is ever a viewer's session, and a session is never either token: each
  credential is accepted only on its own routes.

Sessions live in this process's memory: a restart signs every viewer out.
"""

from __future__ import annotations

import hmac
import html
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from base64 import urlsafe_b64encode
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from typing import Any

import jwt

from starpulse.config import OidcSettings

__all__ = ["ENGINE", "INSTANCE", "PUBLIC", "ROUTES", "SESSION_S", "VIEWER", "Gate", "build"]

PUBLIC, VIEWER, INSTANCE, ENGINE = "public", "viewer", "instance", "engine"
#: The routes that are not viewer routes. The insights routes join it as `ENGINE` routes in their own slice.
ROUTES: Mapping[str, str] = {"/auth/login": PUBLIC, "/auth/callback": PUBLIC, "/api/runs/events": INSTANCE}
#: How long a session lasts: a working day, after which the viewer signs in again.
SESSION_S = 8 * 3600
#: How long a started sign-in may take before its state is forgotten.
_LOGIN_S = 600
#: Sign-ins started and sessions held are bounded, so an unauthenticated caller cannot fill the process's memory.
_LIMIT = 10_000
_SESSION_COOKIE = "starpulse_session"
_LOGIN_COOKIE = "starpulse_login"
#: Asymmetric algorithms only: a token signed with a shared secret must never verify against the issuer's public key.
_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"]
_TIMEOUT_S = 10


class SignInError(Exception):
    """A sign-in that cannot complete; `status` is what the viewer is answered with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class _Login:
    nonce: str
    verifier: str
    expires: float


def _challenge(verifier: str) -> str:
    return urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _bearer(header: str | None) -> str | None:
    scheme, _, token = (header or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


class Gate:
    """Admit or answer each request: `gate(handler)` is True when the route may serve it, and False once the gate has
    answered it itself (a refusal, or a step of the sign-in)."""

    def __init__(
        self,
        settings: OidcSettings,
        client_secret: str,
        engine_token: str | None = None,
        routes: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._secret = client_secret
        self._engine_token = engine_token
        self._routes = {**ROUTES, **(routes or {})}
        self._clock = clock
        self._secure = settings.redirect_uri.startswith("https://")
        self._lock = threading.Lock()
        self._discovery = threading.Lock()
        self._logins: dict[str, _Login] = {}
        self._sessions: dict[str, float] = {}
        self._metadata: dict[str, Any] | None = None
        self._keys: jwt.PyJWKClient | None = None

    def __call__(self, handler: BaseHTTPRequestHandler) -> bool:
        url = urllib.parse.urlsplit(handler.path)
        access = self._routes.get(url.path, VIEWER)
        if access == PUBLIC:
            self._sign_in(handler, url)
            return False
        if access == INSTANCE:
            return True  # the route checks the instance's own token
        if access == ENGINE:
            token = _bearer(handler.headers.get("Authorization"))
            if self._engine_token and token and hmac.compare_digest(token, self._engine_token):
                return True
            self._refuse(handler, "an engine token is required")
            return False
        if self._signed_in(handler):
            return True
        self._refuse(handler, "sign in required")
        return False

    # -- sessions

    def _cookies(self, handler: BaseHTTPRequestHandler) -> SimpleCookie:
        cookies: SimpleCookie = SimpleCookie()
        try:
            cookies.load(handler.headers.get("Cookie", ""))
        except ValueError:  # a malformed Cookie header is no cookie
            return SimpleCookie()
        return cookies

    def _signed_in(self, handler: BaseHTTPRequestHandler) -> bool:
        morsel = self._cookies(handler).get(_SESSION_COOKIE)
        with self._lock:
            expires = self._sessions.get(morsel.value) if morsel else None
            if expires is not None and expires <= self._clock():
                del self._sessions[morsel.value]  # type: ignore[union-attr]
                return False
            return expires is not None

    def _open_session(self) -> str:
        now = self._clock()
        with self._lock:
            for sid in [sid for sid, expires in self._sessions.items() if expires <= now]:
                del self._sessions[sid]
            while len(self._sessions) >= _LIMIT:
                del self._sessions[next(iter(self._sessions))]
            sid = secrets.token_urlsafe(32)
            self._sessions[sid] = now + SESSION_S
            return sid

    def _cookie(self, name: str, value: str, max_age: int, path: str) -> str:
        secure = "; Secure" if self._secure else ""
        return f"{name}={value}; HttpOnly; SameSite=Lax; Path={path}; Max-Age={max_age}{secure}"

    # -- answers

    def _answer(
        self,
        handler: BaseHTTPRequestHandler,
        status: int,
        body: bytes,
        kind: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", kind)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            handler.send_header(name, value)
        handler.end_headers()
        if handler.command != "HEAD":
            handler.wfile.write(body)

    def _refuse(self, handler: BaseHTTPRequestHandler, message: str) -> None:
        """401: JSON for an API caller, a page with the sign-in link for a browser asking for HTML."""
        if "text/html" in handler.headers.get("Accept", ""):
            page = (
                f'<!doctype html><title>Sign in</title><p>{html.escape(message)}. <a href="/auth/login">Sign in</a></p>'
            )
            self._answer(handler, 401, page.encode(), "text/html; charset=utf-8")
            return
        body = json.dumps({"error": message, "signIn": "/auth/login"}).encode()
        self._answer(handler, 401, body, "application/json")

    def _page(
        self,
        handler: BaseHTTPRequestHandler,
        status: int,
        title: str,
        message: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        page = f"<!doctype html><title>{html.escape(title)}</title><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>"
        self._answer(handler, status, page.encode(), "text/html; charset=utf-8", headers)

    # -- the sign-in

    def _sign_in(self, handler: BaseHTTPRequestHandler, url: urllib.parse.SplitResult) -> None:
        if handler.command != "GET":
            self._answer(handler, 405, b"", "text/plain", {"Allow": "GET"})
            return
        try:
            if url.path == "/auth/login":
                self._start(handler)
            else:
                self._finish(handler, urllib.parse.parse_qs(url.query))
        except SignInError as exc:
            self._page(handler, exc.status, "Sign-in failed", str(exc))

    def _discover(self) -> dict[str, Any]:
        with self._discovery:  # one fetch, while sessions and sign-ins go on under `_lock`
            if self._metadata is None:
                target = f"{self._settings.issuer.rstrip('/')}/.well-known/openid-configuration"
                metadata = self._fetch(target)
                if metadata.get("issuer") != self._settings.issuer:
                    raise SignInError(502, "the issuer's metadata names a different issuer than the config")
                self._metadata = metadata
                self._keys = jwt.PyJWKClient(metadata["jwks_uri"], timeout=_TIMEOUT_S)
            return self._metadata

    def _fetch(self, target: str, form: Mapping[str, str] | None = None) -> dict[str, Any]:
        request = urllib.request.Request(target, data=urllib.parse.urlencode(form).encode() if form else None)
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                answer = json.load(resp)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise SignInError(502, f"the issuer did not answer: {exc.__class__.__name__}") from exc
        if not isinstance(answer, dict):
            raise SignInError(502, "the issuer's answer is not a JSON object")
        return answer

    def _start(self, handler: BaseHTTPRequestHandler) -> None:
        metadata = self._discover()
        state, nonce, verifier = (secrets.token_urlsafe(n) for n in (24, 24, 48))
        now = self._clock()
        with self._lock:
            for key in [key for key, login in self._logins.items() if login.expires <= now]:
                del self._logins[key]
            while len(self._logins) >= _LIMIT:
                del self._logins[next(iter(self._logins))]
            self._logins[state] = _Login(nonce, verifier, now + _LOGIN_S)
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": self._settings.client_id,
                "redirect_uri": self._settings.redirect_uri,
                "scope": " ".join(self._settings.scopes),
                "state": state,
                "nonce": nonce,
                "code_challenge": _challenge(verifier),
                "code_challenge_method": "S256",
            }
        )
        self._answer(
            handler,
            302,
            b"",
            "text/plain",
            {
                "Location": f"{metadata['authorization_endpoint']}?{query}",
                "Set-Cookie": self._cookie(_LOGIN_COOKIE, state, _LOGIN_S, "/auth"),
            },
        )

    def _finish(self, handler: BaseHTTPRequestHandler, query: dict[str, list[str]]) -> None:
        state = query.get("state", [""])[0]
        cookie = self._cookies(handler).get(_LOGIN_COOKIE)
        with self._lock:
            login = self._logins.pop(state, None) if state else None
        if login is None or login.expires <= self._clock() or not (cookie and hmac.compare_digest(cookie.value, state)):
            raise SignInError(400, "this sign-in was not started here, or has expired; start again")
        if "error" in query:
            raise SignInError(403, f"the issuer refused the sign-in: {query['error'][0]}")
        if not (code := query.get("code", [""])[0]):
            raise SignInError(400, "the issuer sent no code")
        claims = self._claims(code, login)
        who = str(claims.get("email") or claims.get("preferred_username") or claims["sub"])
        held = claims.get(self._settings.groups_claim)
        groups = (
            {held}
            if isinstance(held, str)
            else {g for g in held if isinstance(g, str)}
            if isinstance(held, list)
            else set()
        )
        if not groups & set(self._settings.allowed_groups):
            allowed = ", ".join(self._settings.allowed_groups)
            self._page(
                handler,
                403,
                "Access refused",
                f"{who} is not a member of an allowed group. Allowed groups: {allowed}.",
                {"Set-Cookie": self._cookie(_LOGIN_COOKIE, "", 0, "/auth")},
            )
            return
        session = self._open_session()
        handler.send_response(302)
        handler.send_header("Location", "/")
        handler.send_header("Set-Cookie", self._cookie(_SESSION_COOKIE, session, SESSION_S, "/"))
        handler.send_header("Set-Cookie", self._cookie(_LOGIN_COOKIE, "", 0, "/auth"))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    def _claims(self, code: str, login: _Login) -> dict[str, Any]:
        """The verified claims of the ID token the issuer gives for `code`."""
        metadata = self._discover()
        answer = self._fetch(
            metadata["token_endpoint"],
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._settings.redirect_uri,
                "client_id": self._settings.client_id,
                "client_secret": self._secret,
                "code_verifier": login.verifier,
            },
        )
        token = answer.get("id_token")
        if not isinstance(token, str) or self._keys is None:
            raise SignInError(502, "the issuer returned no ID token")
        try:
            key = self._keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=_ALGORITHMS,
                audience=self._settings.client_id,
                issuer=self._settings.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise SignInError(403, f"the ID token is not valid: {exc.__class__.__name__}") from exc
        if not hmac.compare_digest(str(claims.get("nonce", "")), login.nonce):
            raise SignInError(403, "the ID token answers a different sign-in (nonce)")
        return claims


def build(settings: OidcSettings, environ: Mapping[str, str], instance_tokens: Mapping[str, str]) -> Gate:
    """The gate `settings` describe, with the client secret and engine token read from the variables they name.

    Raises `ValueError` naming a variable that is unset, and the instance whose token equals the engine's, since a
    token must say whose it is."""
    secret = environ.get(settings.client_secret_env)
    if not secret:
        raise ValueError(f"oidc: {settings.client_secret_env} is not set")
    engine = None
    if settings.engine_token_env:
        if not (engine := environ.get(settings.engine_token_env)):
            raise ValueError(f"oidc: {settings.engine_token_env} is not set")
        if twin := next((name for name, token in instance_tokens.items() if hmac.compare_digest(token, engine)), None):
            raise ValueError(f"oidc: the engine token and instance {twin} hold the same token; each needs its own")
    return Gate(settings, secret, engine)
