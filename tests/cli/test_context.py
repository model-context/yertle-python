"""Tests for org resolution.

Precedence is the whole point of this module, so each rung of the chain gets
its own case.
"""

import json

import pytest
import typer

from yertle.cli._context import (
    ORG_ENV_VAR,
    ResolvedOrg,
    explicit_node_org,
    resolve_org,
    resolve_org_setting,
)
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


def _old_config(**keys: str) -> None:
    """A config file as an earlier version left it: `orgs use` added `org`."""
    auth_mod.CONFIG_PATH.write_text(json.dumps(keys))


def test_a_saved_org_is_not_used(capsys: pytest.CaptureFixture[str]) -> None:
    """The default `orgs use` saved no longer narrows anything."""
    _old_config(org=ORG)
    assert resolve_org(None) == "all"


def test_a_saved_org_is_removed_once_and_said_so(capsys: pytest.CaptureFixture[str]) -> None:
    _old_config(api_url="https://api.example.test", token="yrt_secret", org=ORG)

    resolve_org(None)
    first = capsys.readouterr()
    resolve_org(None)
    second = capsys.readouterr()

    # Said on stderr, so `--format json` stays clean, and with the way back.
    assert first.out == ""
    assert "Removed the default organization saved by `yertle orgs use`" in first.err
    assert f"--org {ORG[:8]}" in first.err and f"{ORG_ENV_VAR}={ORG[:8]}" in first.err
    # Once: the key is gone, so there is nothing to say the second time.
    assert second.err == ""
    assert json.loads(auth_mod.CONFIG_PATH.read_text()) == {
        "api_url": "https://api.example.test",
        "token": "yrt_secret",
    }


def test_a_saved_org_is_removed_even_when_a_flag_wins(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _old_config(org=OTHER)
    assert resolve_org(ORG) == ORG
    assert "Removed the default organization" in capsys.readouterr().err
    assert "org" not in json.loads(auth_mod.CONFIG_PATH.read_text())


def test_provenance_reports_the_winning_rung(monkeypatch: pytest.MonkeyPatch) -> None:
    """`auth status` renders this, so each rung must be distinguishable."""
    assert resolve_org_setting().source is Source.DEFAULT

    monkeypatch.setenv(ORG_ENV_VAR, OTHER)
    assert resolve_org_setting().source is Source.ENV

    assert resolve_org_setting(ORG).source is Source.FLAG


def test_a_node_command_takes_the_flag_then_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ORG_ENV_VAR, OTHER)
    assert explicit_node_org() == ResolvedOrg(OTHER, Source.ENV)
    assert explicit_node_org(ORG) == ResolvedOrg(ORG, Source.FLAG)


@pytest.mark.parametrize("value", ["all", "  ", ""])
def test_all_or_blank_names_no_org_for_a_node_command(value: str) -> None:
    assert explicit_node_org(value) is None
