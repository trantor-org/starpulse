"""The pull request refresh route's answers: who may ask, what may be asked, and what reaches the store's thread."""

from __future__ import annotations

import json

import pytest

from starpulse._internal.pulls.pull_refresh import PullRefresh

TOKEN = "refresh-secret"
TRACKED = {"acme/widgets"}


class Asked:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def __call__(self, repo: str, number: int) -> bool:
        self.calls.append((repo, number))
        return repo in TRACKED


@pytest.fixture
def asked() -> Asked:
    return Asked()


@pytest.fixture
def refresh(asked: Asked) -> PullRefresh:
    return PullRefresh(TOKEN, asked)


def body(**fields: object) -> bytes:
    return json.dumps({"repo": "acme/widgets", "number": 9} | fields).encode()


def test_a_request_with_the_token_for_a_tracked_repository_is_queued_and_answered_202(
    refresh: PullRefresh, asked: Asked
) -> None:
    assert refresh(f"Bearer {TOKEN}", body()) == (202, {"accepted": True})
    assert asked.calls == [("acme/widgets", 9)]


@pytest.mark.parametrize("authorization", [None, "", "Bearer", "Bearer wrong", f"Bearer {TOKEN}-", f"Basic {TOKEN}"])
def test_a_missing_or_wrong_credential_answers_401_and_asks_for_nothing(
    refresh: PullRefresh, asked: Asked, authorization: str | None
) -> None:
    status, _ = refresh(authorization, body())

    assert status == 401
    assert asked.calls == []


def test_a_repository_the_instance_does_not_track_answers_403(refresh: PullRefresh) -> None:
    status, answer = refresh(f"Bearer {TOKEN}", body(repo="evil/other"))

    assert status == 403
    assert "evil/other" in answer["error"]


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"[]",
        body(repo=""),
        body(repo="widgets"),
        body(number=0),
        body(number=-3),
        body(number="9"),
        body(number=True),
        json.dumps({"repo": "acme/widgets"}).encode(),
    ],
)
def test_a_body_that_is_not_a_repository_and_a_pull_request_number_answers_400_and_asks_for_nothing(
    refresh: PullRefresh, asked: Asked, raw: bytes
) -> None:
    status, _ = refresh(f"Bearer {TOKEN}", raw)

    assert status == 400
    assert asked.calls == []
