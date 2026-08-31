"""Smoke tests for the Typer CLI."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from yertle.sre import __version__
from yertle.sre.cli import app
from yertle.sre.cli.app import _load_settings

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "yertle-sre" in result.stdout
    assert "ask" in result.stdout
    assert "repl" in result.stdout
    assert "status" in result.stdout


def test_status_command(monkeypatch):
    # No real CLIs in the test env → all probes report "not authenticated".
    # The command should still exit 0 and print all four provider names.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    for name in ("ANTHROPIC_API_KEY", "yertle", "aws", "gh"):
        assert name in result.stdout


def test_ask_rejects_empty_question():
    # Empty question would otherwise reach Anthropic and 400 with a confusing
    # traceback. We should fail fast with a clear error.
    result = runner.invoke(app, ["ask", ""])
    assert result.exit_code == 2
    output = result.stdout + (result.stderr or "")
    assert "cannot be empty" in output


def test_ask_rejects_whitespace_only_question():
    result = runner.invoke(app, ["ask", "   "])
    assert result.exit_code == 2
    output = result.stdout + (result.stderr or "")
    assert "cannot be empty" in output


def test_load_settings_reports_bad_config_and_exits_2(monkeypatch, capsys):
    # A malformed value in the environment must surface as a one-line message
    # and exit 2 — not as a pydantic traceback. This is the CLI's only
    # deliberate blind `except`, so it needs a test that pins the behavior.
    monkeypatch.setenv("YERTLE_SRE_MAX_ITERATIONS", "not-a-number")

    with pytest.raises(SystemExit) as excinfo:
        _load_settings(model=None, max_iterations=None)

    assert excinfo.value.code == 2
    assert "Configuration error" in capsys.readouterr().err
