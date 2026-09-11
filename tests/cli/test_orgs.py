"""Tests for the `yertle orgs` command group.

Mocks the *wire* layer rather than the SDK, so these exercise the real
CLI → `yertle.orgs` → `yertle_client` path. Patching `yertle.orgs.list`
itself would pass even if the CLI stopped calling the SDK at all.
"""

import datetime
import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from yertle_client.errors import UnexpectedStatus
from yertle_client.models import OrganizationListResponse, OrganizationResponse

from yertle.cli._context import ORG_ENV_VAR
from yertle.cli.main import app
from yertle.shared import auth as auth_mod

runner = CliRunner()


def _fake_response() -> OrganizationListResponse:
    now = datetime.datetime(2026, 5, 19, tzinfo=datetime.UTC)
    return OrganizationListResponse(
        organizations=[
            OrganizationResponse(
                id="org-1",
                name="Acme",
                public_id="acme",
                created_at=now,
                updated_at=now,
            ),
            OrganizationResponse(
                id="org-2",
                name="Beta Corp",
                public_id="beta",
                created_at=now,
                updated_at=now,
            ),
        ],
        total=2,
    )


@patch("yertle.orgs.list_organizations_orgs_get.sync", return_value=_fake_response())
@patch("yertle._client.get_client", return_value=object())
def test_orgs_list_table_format(_get_client, _sync) -> None:
    result = runner.invoke(app, ["orgs", "list"])
    assert result.exit_code == 0, result.output
    assert "Acme" in result.output
    assert "Beta Corp" in result.output
    assert "Organizations (2)" in result.output


@patch("yertle.orgs.list_organizations_orgs_get.sync", return_value=_fake_response())
@patch("yertle._client.get_client", return_value=object())
def test_orgs_list_json_format(_get_client, _sync) -> None:
    result = runner.invoke(app, ["orgs", "list", "--format", "json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert len(parsed) == 2
    assert parsed[0]["name"] == "Acme"


def test_orgs_is_a_group_not_a_command() -> None:
    """A bare noun prints help, the way `gh repo` does — it never lists."""
    result = runner.invoke(app, ["orgs"])
    assert "list" in result.output
    assert "Acme" not in result.output


@pytest.mark.parametrize("bad", ["xml", "yaml", ""])
def test_orgs_list_rejects_an_unknown_format(bad: str) -> None:
    """`--format` is an enum, so a typo errors instead of silently tabling."""
    result = runner.invoke(app, ["orgs", "list", "--format", bad])
    assert result.exit_code != 0


@patch(
    "yertle.orgs.list_organizations_orgs_get.sync",
    side_effect=UnexpectedStatus(401, b'{"detail":"Invalid or expired token"}'),
)
@patch("yertle._client.get_client", return_value=object())
def test_orgs_list_renders_an_api_error_as_a_sentence(_get_client, _sync) -> None:
    """A wire failure exits 1 with prose naming the backend, not a traceback."""
    result = runner.invoke(app, ["orgs", "list"])
    assert result.exit_code == 1
    assert "401 Unauthorized" in result.output
    assert "Traceback" not in result.output


# --- `yertle orgs use` -------------------------------------------------------


@pytest.fixture
def isolated_config(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """A config file the test owns, and no ambient $YERTLE_ORG."""
    path = tmp_path / "config.json"
    monkeypatch.setattr(auth_mod, "CONFIG_PATH", path)
    monkeypatch.delenv(ORG_ENV_VAR, raising=False)
    return path


ORG_ID = "8f14e45f-ceea-467a-9575-28db8d0dc4db"


def test_orgs_use_persists_the_org(isolated_config) -> None:
    result = runner.invoke(app, ["orgs", "use", ORG_ID])
    assert result.exit_code == 0, result.output
    assert ORG_ID in result.output
    assert json.loads(isolated_config.read_text())["org"] == ORG_ID


def test_orgs_use_all_resets(isolated_config) -> None:
    runner.invoke(app, ["orgs", "use", ORG_ID])
    result = runner.invoke(app, ["orgs", "use", "all"])
    assert result.exit_code == 0, result.output
    assert "every org" in result.output
    assert json.loads(isolated_config.read_text())["org"] == "all"


def test_orgs_use_rejects_a_malformed_id(isolated_config) -> None:
    result = runner.invoke(app, ["orgs", "use", "acme-corp"])
    assert result.exit_code == 1
    assert "not an organization id" in result.output
    assert not isolated_config.exists(), "a rejected id must not be written"


def test_orgs_use_keeps_credentials(isolated_config) -> None:
    """The whole risk of writing to this file is clobbering the token."""
    auth_mod.save_credentials(api_url="https://api.example.test", token="yrt_secret")
    runner.invoke(app, ["orgs", "use", ORG_ID])
    stored = json.loads(isolated_config.read_text())
    assert stored["token"] == "yrt_secret"
    assert stored["api_url"] == "https://api.example.test"
    assert stored["org"] == ORG_ID
