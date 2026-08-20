"""Tests for credential resolution in `yertle.shared.auth`."""

import json
import os
import stat
from collections.abc import Iterator
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


# ---------------------------------------------------------------------------
# `resolve()` — provenance reporting behind `yertle auth status`
# ---------------------------------------------------------------------------


def test_resolve_reports_env_as_source_for_both_keys(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text(json.dumps({"token": "cfg-token", "api_url": "https://cfg.example"}))

    monkeypatch.setenv("YERTLE_TOKEN", "env-token")
    monkeypatch.setenv("YERTLE_API_URL", "https://env.example")

    resolved = auth_mod.resolve()

    assert resolved.token == "env-token"
    assert resolved.api_url == "https://env.example"
    assert resolved.token_source is auth_mod.Source.ENV
    assert resolved.api_url_source is auth_mod.Source.ENV


def test_resolve_reports_mixed_sources(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The footgun case: config-file token aimed at an env-var URL."""
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text(json.dumps({"token": "cfg-token", "api_url": "https://cfg.example"}))

    _clear_env(monkeypatch)
    monkeypatch.setenv("YERTLE_API_URL", "http://localhost:8000")

    resolved = auth_mod.resolve()

    assert resolved.token == "cfg-token"
    assert resolved.token_source is auth_mod.Source.CONFIG
    assert resolved.api_url == "http://localhost:8000"
    assert resolved.api_url_source is auth_mod.Source.ENV


def test_resolve_reports_default_url(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("YERTLE_TOKEN", "env-token")

    resolved = auth_mod.resolve()

    assert resolved.api_url == auth_mod.DEFAULT_API_URL
    assert resolved.api_url_source is auth_mod.Source.DEFAULT


def test_resolve_reports_missing_token_without_raising(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`resolve()` must not raise — `auth status` renders the unauthenticated state."""
    _clear_env(monkeypatch)

    resolved = auth_mod.resolve()

    assert resolved.token is None
    assert resolved.token_source is auth_mod.Source.MISSING
    assert resolved.api_url_source is auth_mod.Source.DEFAULT


# ---------------------------------------------------------------------------
# `save_credentials` — permissions, merging, atomicity
# ---------------------------------------------------------------------------


@pytest.fixture
def loose_umask() -> Iterator[None]:
    """Run under umask 022 — the common default, and where the bug shows.

    On a machine whose interactive umask is already 077 these assertions pass
    against the unfixed code, so pinning the umask is what makes them real.
    """
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_save_credentials_writes_owner_only_file(
    isolated_config: Path,
    loose_umask: None,
) -> None:
    auth_mod.save_credentials(api_url="https://example.test", token="yrt_secret")

    assert _mode(isolated_config) == 0o600


def test_save_credentials_creates_owner_only_directory(
    isolated_config: Path,
    loose_umask: None,
) -> None:
    auth_mod.save_credentials(api_url="https://example.test", token="yrt_secret")

    assert _mode(isolated_config.parent) == 0o700


def test_save_credentials_tightens_a_preexisting_loose_file(
    isolated_config: Path,
    loose_umask: None,
) -> None:
    """Upgrade path: a config an older version wrote world-readable gets fixed."""
    isolated_config.parent.mkdir(parents=True)
    isolated_config.parent.chmod(0o755)
    isolated_config.write_text(json.dumps({"token": "old", "api_url": "https://old.test"}))
    isolated_config.chmod(0o644)

    auth_mod.save_credentials(api_url="https://example.test", token="yrt_secret")

    assert _mode(isolated_config) == 0o600
    assert _mode(isolated_config.parent) == 0o700


def test_save_credentials_preserves_unknown_keys(isolated_config: Path) -> None:
    """A re-login must not drop config this version doesn't know about."""
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text(
        json.dumps({"token": "old", "api_url": "https://old.test", "default_org": "org-1"})
    )

    auth_mod.save_credentials(api_url="https://new.test", token="yrt_new")

    saved = json.loads(isolated_config.read_text())
    assert saved == {
        "token": "yrt_new",
        "api_url": "https://new.test",
        "default_org": "org-1",
    }


def test_failed_write_leaves_the_existing_config_intact(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Atomicity: a crash mid-write must not truncate working credentials."""
    isolated_config.parent.mkdir(parents=True)
    original = json.dumps({"token": "good", "api_url": "https://good.test"})
    isolated_config.write_text(original)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(auth_mod.json, "dump", boom)

    with pytest.raises(OSError, match="disk full"):
        auth_mod.save_credentials(api_url="https://new.test", token="yrt_new")

    assert isolated_config.read_text() == original
    leftovers = list(isolated_config.parent.glob(".config-*"))
    assert leftovers == [], f"temp file not cleaned up: {leftovers}"


def test_corrupt_config_raises_auth_error_not_traceback(isolated_config: Path) -> None:
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text("{not json")

    with pytest.raises(auth_mod.AuthError, match="not valid JSON"):
        auth_mod.resolve()
