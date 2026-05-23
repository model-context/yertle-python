"""Tests for the auth/connection probes."""

from __future__ import annotations

from tests.sre.conftest import FakeCompleted
from yertle.sre.cli.status import (
    probe_all,
    probe_anthropic,
    probe_aws,
    probe_gh,
    probe_yertle,
)


def test_probe_anthropic_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    result = probe_anthropic()
    assert result.ok
    assert result.detail == "set"


def test_probe_anthropic_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = probe_anthropic()
    assert not result.ok
    assert "ANTHROPIC_API_KEY" in result.detail


def test_probe_yertle_success(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="[]", stderr="", returncode=0))
    result = probe_yertle()
    assert result.ok
    assert result.detail == "authenticated"


def test_probe_yertle_failure(fake_cli):
    fake_cli(
        lambda _argv: FakeCompleted(stdout="", stderr="auth: not logged in", returncode=1),
    )
    result = probe_yertle()
    assert not result.ok
    assert "yertle login" in result.detail


def test_probe_aws_success_extracts_arn(fake_cli, monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    fake_cli(
        lambda _argv: FakeCompleted(
            stdout='{"Arn":"arn:aws:iam::1234567890:user/x","UserId":"AID"}',
            stderr="",
            returncode=0,
        ),
    )
    result = probe_aws()
    assert result.ok
    assert "arn:aws:iam::1234567890:user/x" in result.detail
    assert "default" in result.detail


def test_probe_aws_uses_aws_profile_env(fake_cli, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "prod")
    fake_cli(
        lambda _argv: FakeCompleted(
            stdout='{"Arn":"arn:aws:iam::9999:user/p"}',
            stderr="",
            returncode=0,
        ),
    )
    result = probe_aws()
    assert result.ok
    assert "(profile: prod)" in result.detail


def test_probe_aws_failure(fake_cli):
    fake_cli(
        lambda _argv: FakeCompleted(
            stdout="",
            stderr="Unable to locate credentials",
            returncode=255,
        ),
    )
    result = probe_aws()
    assert not result.ok
    assert "aws configure" in result.detail


def test_probe_aws_unparseable_stdout_falls_back(fake_cli, monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    fake_cli(
        lambda _argv: FakeCompleted(stdout="not-json", stderr="", returncode=0),
    )
    result = probe_aws()
    assert result.ok
    assert "unknown principal" in result.detail


def test_probe_gh_success(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="", stderr="", returncode=0))
    result = probe_gh()
    assert result.ok


def test_probe_gh_failure(fake_cli):
    fake_cli(
        lambda _argv: FakeCompleted(stdout="", stderr="not logged in", returncode=1),
    )
    result = probe_gh()
    assert not result.ok
    assert "gh auth login" in result.detail


def test_probe_all_returns_four_results(fake_cli, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    fake_cli(lambda _argv: FakeCompleted(stdout="[]", stderr="", returncode=0))
    results = probe_all()
    names = [r.name for r in results]
    assert names == ["ANTHROPIC_API_KEY", "yertle", "aws", "gh"]
