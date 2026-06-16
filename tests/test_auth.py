"""Tests for credential resolution in `yertle.shared.auth`."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from yertle.shared import auth as auth_mod


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point CONFIG_PATH at a temp file so tests don't touch the real ~/.yertle/."""
    cfg_path = tmp_path / ".yertle" / "config.json"
    monkeypatch.setattr(auth_mod, "CONFIG_PATH", cfg_path)
    return cfg_path


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YERTLE_TOKEN", raising=False)
    monkeypatch.delenv("YERTLE_API_URL", raising=False)


def test_token_env_alone_defaults_to_prod_url(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`YERTLE_TOKEN` alone is sufficient — URL defaults to prod."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("YERTLE_TOKEN", "yrt_abc")

    with patch.object(auth_mod, "AuthenticatedClient") as mock_factory:
        auth_mod.get_client()

    mock_factory.assert_called_once_with(
        base_url=auth_mod.DEFAULT_API_URL,
        token="yrt_abc",
        raise_on_unexpected_status=True,
    )


def test_both_env_vars_take_precedence_over_config(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text(json.dumps({"token": "cfg-token", "api_url": "https://cfg.example"}))

    monkeypatch.setenv("YERTLE_TOKEN", "env-token")
    monkeypatch.setenv("YERTLE_API_URL", "https://env.example")

    with patch.object(auth_mod, "AuthenticatedClient") as mock_factory:
        auth_mod.get_client()

    mock_factory.assert_called_once_with(
        base_url="https://env.example", token="env-token", raise_on_unexpected_status=True
    )


def test_env_token_overrides_config_token_but_url_falls_back(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-key resolution: env wins, config fills gaps."""
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text(
        json.dumps({"token": "cfg-token", "api_url": "http://localhost:8000"})
    )

    _clear_env(monkeypatch)
    monkeypatch.setenv("YERTLE_TOKEN", "env-token")  # only token set

    with patch.object(auth_mod, "AuthenticatedClient") as mock_factory:
        auth_mod.get_client()

    mock_factory.assert_called_once_with(
        base_url="http://localhost:8000", token="env-token", raise_on_unexpected_status=True
    )


def test_config_only(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text(json.dumps({"token": "cfg-token", "api_url": "https://cfg.example"}))

    _clear_env(monkeypatch)

    with patch.object(auth_mod, "AuthenticatedClient") as mock_factory:
        auth_mod.get_client()

    mock_factory.assert_called_once_with(
        base_url="https://cfg.example", token="cfg-token", raise_on_unexpected_status=True
    )


def test_raises_auth_error_when_nothing_set(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    # isolated_config doesn't exist (no write)

    with pytest.raises(auth_mod.AuthError, match="Not authenticated"):
        auth_mod.get_client()
