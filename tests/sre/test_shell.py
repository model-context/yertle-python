"""Unit tests for the subprocess chokepoint."""

from __future__ import annotations

from tests.sre.conftest import FakeCompleted
from yertle.sre.tools._shell import TRUNCATION_MARKER, run_cli


def test_run_cli_success(fake_cli):
    fake_cli(lambda _argv: FakeCompleted(stdout="hello", stderr="", returncode=0))
    result = run_cli(["yertle", "orgs"])
    assert result.ok is True
    assert result.stdout == "hello"
    assert result.exit_code == 0
    assert result.truncated is False


def test_run_cli_failure_includes_summary(fake_cli):
    fake_cli(
        lambda _argv: FakeCompleted(
            stdout="",
            stderr="auth: token expired\nrun yertle login",
            returncode=1,
        ),
    )
    result = run_cli(["yertle", "orgs"])
    assert result.ok is False
    assert "auth: token expired" in result.error_summary()


def test_run_cli_truncates_long_output(fake_cli):
    big = "x" * 50_000
    fake_cli(lambda _argv: FakeCompleted(stdout=big, stderr="", returncode=0))
    result = run_cli(["yertle", "orgs"], max_output=100)
    assert result.truncated is True
    assert result.stdout.endswith(TRUNCATION_MARKER)
    assert len(result.stdout) <= 100 + len(TRUNCATION_MARKER)


def test_run_cli_missing_executable(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    result = run_cli(["nonexistent-binary"])
    assert result.ok is False
    assert "executable not found" in result.stderr
    assert result.exit_code == 127
