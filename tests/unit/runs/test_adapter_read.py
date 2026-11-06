from __future__ import annotations

import pytest

from starpulse.runs.adapters.outbound import dagu, systemd


def test_dagu_read_lists_every_dag_of_the_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(dagu, "dags", lambda url, *a, **k: seen.append(url) or [{"name": "nightly"}])

    assert dagu.read("http://dagu") == [{"name": "nightly"}]
    assert seen == ["http://dagu"]


def test_systemd_read_lists_the_allowlist_with_the_real_systemctl(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(systemd, "listing", lambda run, url: seen.append(url) or [{"name": "backup"}])

    assert systemd.read("backup") == [{"name": "backup"}]
    assert seen == ["backup"]


def test_github_actions_read_lists_the_repository_with_a_signed_in_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    from starpulse.runs.adapters.outbound import github_actions

    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(github_actions, "connect", lambda token: f"transport:{token}")
    monkeypatch.setattr(github_actions, "listing", lambda transport, repo: ([{"name": f"{transport}@{repo}"}], []))

    assert github_actions.read("https://github.com/acme/app") == [{"name": "transport:t@acme/app"}]


def test_temporal_read_lists_the_server_without_reporting_to_a_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    from starpulse.runs.adapters.outbound import temporal

    monkeypatch.setattr(temporal.Poller, "listing", lambda self, now: [{"name": self.base}])

    assert temporal.read("http://temporal:8233/") == [{"name": "http://temporal:8233"}]
