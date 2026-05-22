"""Tests for the `yertle orgs` command.

Mocks `yertle_client` so the test runs without a backend or credentials.
"""

import datetime
import json
from unittest.mock import patch

from typer.testing import CliRunner
from yertle_client.models import OrganizationListResponse, OrganizationResponse

from yertle.cli.main import app

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


@patch("yertle.cli.main.list_organizations_orgs_get.sync", return_value=_fake_response())
@patch("yertle.cli.main.get_client", return_value=object())
def test_orgs_table_format(_get_client, _sync) -> None:
    result = runner.invoke(app, ["orgs"])
    assert result.exit_code == 0, result.output
    assert "Acme" in result.output
    assert "Beta Corp" in result.output
    assert "Organizations (2)" in result.output


@patch("yertle.cli.main.list_organizations_orgs_get.sync", return_value=_fake_response())
@patch("yertle.cli.main.get_client", return_value=object())
def test_orgs_json_format(_get_client, _sync) -> None:
    result = runner.invoke(app, ["orgs", "--format", "json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert len(parsed) == 2
    assert parsed[0]["name"] == "Acme"
