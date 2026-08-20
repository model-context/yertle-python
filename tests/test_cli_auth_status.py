"""Tests for the `yertle auth status` command."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from yertle.cli.main import _mask_token, app
from yertle.shared import auth as auth_mod

runner = CliRunner()


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg_path = tmp_path / ".yertle" / "config.json"
    monkeypatch.setattr(auth_mod, "CONFIG_PATH", cfg_path)
    monkeypatch.delenv("YERTLE_TOKEN", raising=False)
    monkeypatch.delenv("YERTLE_API_URL", raising=False)
    return cfg_path


def test_status_shows_env_provenance(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YERTLE_TOKEN", "yrt_abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("YERTLE_API_URL", "http://localhost:8000")

    result = runner.invoke(app, ["auth", "status"])

    assert result.exit_code == 0
    assert "http://localhost:8000" in result.output
    assert "$YERTLE_API_URL" in result.output
    assert "$YERTLE_TOKEN" in result.output


def test_status_never_prints_the_raw_token(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "yrt_abcdefghijklmnopqrstuvwxyz"
    monkeypatch.setenv("YERTLE_TOKEN", secret)

    result = runner.invoke(app, ["auth", "status"])

    assert secret not in result.output
    assert "yrt_abcd" in result.output  # enough to identify which token


def test_status_shows_config_provenance(
    isolated_config: Path,
) -> None:
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text(
        json.dumps({"token": "cfg-token-long-enough", "api_url": "https://cfg.example"})
    )

    result = runner.invoke(app, ["auth", "status"])

    assert result.exit_code == 0
    assert "https://cfg.example" in result.output
    assert "config.json" in result.output


def test_status_exits_nonzero_when_unauthenticated(isolated_config: Path) -> None:
    result = runner.invoke(app, ["auth", "status"])

    assert result.exit_code == 1
    assert "Not authenticated" in result.output


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("yrt_abcdefghijklmnopqrstuvwxyz", "yrt_abcd…wxyz"),
        ("short", "*****"),
        ("exactly-16-chars", "*" * 16),
    ],
)
def test_mask_token(token: str, expected: str) -> None:
    assert _mask_token(token) == expected
