"""Tests for the `yertle auth status` command."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from yertle.cli.commands.auth import _mask_token
from yertle.cli.commands.login import _web_url_for
from yertle.cli.main import app
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


def test_status_does_not_wrap_long_paths_on_a_narrow_console(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: Rich hard-broke the config path mid-token to fit the console.

    Values are URLs and filesystem paths — breaking them across lines makes the
    output neither greppable nor copy-pasteable. Asserts the path appears
    *contiguously*: checking for a substring like `config.json` instead would
    only catch the bug when a line break happened to land inside that literal.
    """
    cfg_path = tmp_path / "a-fairly-long-directory-name-like-ci-produces" / "config.json"
    monkeypatch.setattr(auth_mod, "CONFIG_PATH", cfg_path)
    monkeypatch.delenv("YERTLE_TOKEN", raising=False)
    monkeypatch.delenv("YERTLE_API_URL", raising=False)
    monkeypatch.setenv("COLUMNS", "40")
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(
        json.dumps({"token": "cfg-token-long-enough", "api_url": "https://cfg.example"})
    )

    result = runner.invoke(app, ["auth", "status"])

    assert result.exit_code == 0
    assert str(cfg_path) in result.output
    assert "https://cfg.example" in result.output


@pytest.mark.parametrize(
    ("api_url", "expected"),
    [
        ("https://api.yertle.com", "https://yertle.com"),
        ("https://api.dev.yertle.com", "https://dev.yertle.com"),
        ("http://localhost:8000", "http://localhost:3000"),
        ("http://127.0.0.1:8000", "http://127.0.0.1:3000"),
        ("https://yertle.internal", None),  # can't derive — don't guess
        ("not-a-url", None),
    ],
)
def test_web_url_for(api_url: str, expected: str | None) -> None:
    """PATs are minted in the web app, so login must not point at the API host."""
    assert _web_url_for(api_url) == expected


def test_login_rejects_an_empty_token(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty token would persist a config that resolves as unauthenticated."""
    monkeypatch.setattr("yertle.cli.commands.login.typer.prompt", lambda *a, **k: "   ")

    result = runner.invoke(app, ["login", "--api-url", "http://localhost:8000"])

    assert result.exit_code == 1
    assert not isolated_config.exists()


# --- `yertle login` defaults -------------------------------------------------


def test_login_defaults_to_production(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare `yertle login` should work. Requiring --api-url taxed the common case."""
    monkeypatch.setattr("yertle.cli.commands.login.typer.prompt", lambda *a, **k: "yrt_abc")

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 0, result.output
    assert json.loads(isolated_config.read_text())["api_url"] == auth_mod.DEFAULT_API_URL


def test_login_still_accepts_an_explicit_backend(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flag is for persisting a non-prod choice; $YERTLE_API_URL is for one-offs."""
    monkeypatch.setattr("yertle.cli.commands.login.typer.prompt", lambda *a, **k: "yrt_abc")

    result = runner.invoke(app, ["login", "--api-url", "https://api.dev.yertle.com"])

    assert result.exit_code == 0, result.output
    assert json.loads(isolated_config.read_text())["api_url"] == "https://api.dev.yertle.com"


def test_login_names_the_backend_it_saved(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a default in play, "saved" alone does not say which backend."""
    monkeypatch.setattr("yertle.cli.commands.login.typer.prompt", lambda *a, **k: "yrt_abc")

    result = runner.invoke(app, ["login", "--api-url", "https://api.dev.yertle.com"])

    assert "https://api.dev.yertle.com" in result.output


def test_login_binds_the_token_to_its_backend(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both keys are written together.

    A token is only valid against the backend that issued it. Saving the token
    without the URL would let a dev token resolve against production later and
    fail as an opaque 401 — the exact confusion `auth status` exists to
    diagnose.
    """
    monkeypatch.setattr("yertle.cli.commands.login.typer.prompt", lambda *a, **k: "yrt_dev")

    runner.invoke(app, ["login", "--api-url", "https://api.dev.yertle.com"])

    stored = json.loads(isolated_config.read_text())
    assert stored == {"api_url": "https://api.dev.yertle.com", "token": "yrt_dev"}
