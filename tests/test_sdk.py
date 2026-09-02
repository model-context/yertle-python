"""Smoke tests for the `import yertle` SDK facade.

Mocks the wire layer so the tests run without a backend or credentials.
"""

import datetime
from unittest.mock import patch

import pytest
from yertle_client.models import OrganizationListResponse, OrganizationResponse

import yertle


def _fake_org(org_id: str, name: str) -> OrganizationResponse:
    now = datetime.datetime(2026, 5, 23, tzinfo=datetime.UTC)
    return OrganizationResponse(
        id=org_id,
        name=name,
        public_id=name.lower(),
        created_at=now,
        updated_at=now,
    )


def _fake_list() -> OrganizationListResponse:
    return OrganizationListResponse(
        organizations=[_fake_org("org-1", "Acme"), _fake_org("org-2", "Beta")],
        total=2,
    )


@patch("yertle.orgs.list_organizations_orgs_get.sync", return_value=_fake_list())
@patch("yertle._client.get_client", return_value=object())
def test_orgs_list_unwraps_to_list(_get_client, _sync):
    orgs = yertle.orgs.list()

    assert isinstance(orgs, list)
    assert len(orgs) == 2
    assert orgs[0].name == "Acme"
    assert orgs[1].name == "Beta"


@patch("yertle.orgs.get_organization_orgs_org_id_get.sync", return_value=_fake_org("org-1", "Acme"))
@patch("yertle._client.get_client", return_value=object())
def test_orgs_get_returns_single(_get_client, _sync):
    org = yertle.orgs.get("org-1")

    assert org.id == "org-1"
    assert org.name == "Acme"
    _sync.assert_called_once()
    assert _sync.call_args.kwargs["org_id"] == "org-1"


@patch("yertle.orgs.list_organizations_orgs_get.sync", return_value=_fake_list())
@patch("yertle._client.get_client", return_value=object())
def test_default_client_is_cached(_get_client, _sync):
    yertle.orgs.list()
    yertle.orgs.list()
    yertle.orgs.list()

    # get_client should only be called once across multiple SDK calls
    assert _get_client.call_count == 1


@patch("yertle.orgs.list_organizations_orgs_get.sync", return_value=None)
@patch("yertle._client.get_client", return_value=object())
def test_orgs_list_raises_on_unexpected_response(_get_client, _sync):
    with pytest.raises(RuntimeError, match="Unexpected response"):
        yertle.orgs.list()


@patch("yertle.orgs.list_organizations_orgs_get.sync", return_value=_fake_list())
@patch("yertle._client.get_client")
def test_configure_bypasses_get_client(_get_client, _sync):
    yertle.configure(token="yrt_test", api_url="http://localhost:8000")
    yertle.orgs.list()

    # configure() set the client directly; get_client() should never be called
    _get_client.assert_not_called()

    c = yertle.client()
    assert c.token == "yrt_test"  # pyright: ignore[reportPrivateUsage]
