"""Tests for org resolution.

Precedence is the whole point of this module, so each rung of the chain gets
its own case.
"""

import pytest
import typer

from yertle.cli._context import ORG_ENV_VAR, resolve_org

ORG = "8f14e45f-ceea-467a-9575-28db8d0dc4db"
OTHER = "1c383cd3-0b3f-4e1f-8e2a-9a1f0a0d1c2b"


@pytest.fixture(autouse=True)
def _no_ambient_org(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.delenv(ORG_ENV_VAR, raising=False)


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
