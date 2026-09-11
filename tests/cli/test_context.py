"""Tests for org resolution.

Precedence is the whole point of this module, so each rung of the chain gets
its own case.
"""

import pytest
import typer

from yertle.cli._context import ORG_ENV_VAR, resolve_org, resolve_org_setting
from yertle.shared import auth as auth_mod
from yertle.shared.auth import Source

ORG = "8f14e45f-ceea-467a-9575-28db8d0dc4db"
OTHER = "1c383cd3-0b3f-4e1f-8e2a-9a1f0a0d1c2b"


@pytest.fixture(autouse=True)
def _isolated_context(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """No ambient env var, and a config file the test owns."""
    monkeypatch.delenv(ORG_ENV_VAR, raising=False)
    monkeypatch.setattr(auth_mod, "CONFIG_PATH", tmp_path / "config.json")


def test_flag_wins() -> None:
    assert resolve_org(ORG) == ORG


def test_env_var_is_used_when_no_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ORG_ENV_VAR, ORG)
    assert resolve_org(None) == ORG


def test_flag_beats_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ORG_ENV_VAR, OTHER)
    assert resolve_org(ORG) == ORG


def test_defaults_to_all_orgs() -> None:
    """`yertle nodes list` with no arguments should show you your world."""
    assert resolve_org(None) == "all"


def test_all_is_passed_through() -> None:
    assert resolve_org("all") == "all"


@pytest.mark.parametrize("value", ["  ", "\t"])
def test_blank_values_fall_through_to_the_default(value: str) -> None:
    assert resolve_org(value) == "all"


def test_a_malformed_id_exits_with_a_sentence() -> None:
    """A typo'd id fails here, not as a ValueError from inside the SDK."""
    with pytest.raises(typer.Exit) as excinfo:
        resolve_org("acme-corp")
    assert excinfo.value.exit_code == 1


def _persist(org: str) -> None:
    auth_mod.save_org(org)


def test_config_is_used_when_no_flag_or_env() -> None:
    _persist(ORG)
    assert resolve_org(None) == ORG


def test_env_var_beats_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _persist(ORG)
    monkeypatch.setenv(ORG_ENV_VAR, OTHER)
    assert resolve_org(None) == OTHER


def test_flag_beats_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _persist(OTHER)
    monkeypatch.setenv(ORG_ENV_VAR, OTHER)
    assert resolve_org(ORG) == ORG


def test_provenance_reports_the_winning_rung(monkeypatch: pytest.MonkeyPatch) -> None:
    """`auth status` renders this, so each rung must be distinguishable."""
    assert resolve_org_setting().source is Source.DEFAULT

    _persist(ORG)
    assert resolve_org_setting().source is Source.CONFIG

    monkeypatch.setenv(ORG_ENV_VAR, OTHER)
    assert resolve_org_setting().source is Source.ENV

    assert resolve_org_setting(ORG).source is Source.FLAG


def test_saving_all_resets_to_every_org() -> None:
    """`orgs use all` is how a previous choice is undone."""
    _persist(ORG)
    _persist("all")
    assert resolve_org(None) == "all"


def test_saving_an_org_preserves_credentials() -> None:
    """Writing one setting must not drop another — the config merge path."""
    auth_mod.save_credentials(api_url="https://api.example.test", token="yrt_secret")
    _persist(ORG)
    resolved = auth_mod.resolve()
    assert resolved.token == "yrt_secret"
    assert resolved.api_url == "https://api.example.test"
    assert resolve_org(None) == ORG
