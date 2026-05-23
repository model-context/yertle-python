"""Smoke tests for the `import yertle` SDK facade.

Mocks the wire layer so the tests run without a backend or credentials.
"""

import datetime
from collections.abc import Iterator
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


@pytest.fixture(autouse=True)
def reset_default_client() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Ensure each test starts with a fresh lazy-init cache."""
    yertle._default_client = None  # pyright: ignore[reportPrivateUsage]
    yield
    yertle._default_client = None  # pyright: ignore[reportPrivateUsage]


@patch("yertle.list_organizations_orgs_get.sync", return_value=_fake_list())
@patch("yertle.get_client", return_value=object())
def test_list_orgs_unwraps_to_list(_get_client, _sync):
    orgs = yertle.list_orgs()

    assert isinstance(orgs, list)
    assert len(orgs) == 2
    assert orgs[0].name == "Acme"
    assert orgs[1].name == "Beta"


@patch("yertle.get_organization_orgs_org_id_get.sync", return_value=_fake_org("org-1", "Acme"))
@patch("yertle.get_client", return_value=object())
def test_get_org_returns_single(_get_client, _sync):
    org = yertle.get_org("org-1")

    assert org.id == "org-1"
    assert org.name == "Acme"
    _sync.assert_called_once()
    assert _sync.call_args.kwargs["org_id"] == "org-1"


@patch("yertle.list_organizations_orgs_get.sync", return_value=_fake_list())
@patch("yertle.get_client", return_value=object())
def test_default_client_is_cached(_get_client, _sync):
    yertle.list_orgs()
    yertle.list_orgs()
    yertle.list_orgs()

    # get_client should only be called once across multiple SDK calls
    assert _get_client.call_count == 1


@patch("yertle.list_organizations_orgs_get.sync", return_value=None)
@patch("yertle.get_client", return_value=object())
def test_list_orgs_raises_on_unexpected_response(_get_client, _sync):
    with pytest.raises(RuntimeError, match="Unexpected response"):
        yertle.list_orgs()
