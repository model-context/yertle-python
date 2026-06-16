"""Organizations resource. Imported as `yertle.orgs`.

    >>> import yertle
    >>> for org in yertle.orgs.list():
    ...     print(org.name)
    >>> acme = yertle.orgs.get("org-1")

The module IS the namespace; we use plain functions rather than a class
wrapper. The `list` function name shadows the `list` builtin within this
module's local scope — acceptable tradeoff for a small file that doesn't
need to construct lists in the builtin sense.
"""

from __future__ import annotations

import builtins

from yertle_client.api.organizations import (
    get_organization_orgs_org_id_get,
    list_organizations_orgs_get,
)
from yertle_client.models import OrganizationListResponse, OrganizationResponse

from yertle._client import client

__all__ = ["get", "list"]


# `list` shadows the builtin inside this module — annotations reference
# `builtins.list` explicitly so type-checkers don't see the function
# self-referencing. The shadow is only visible when editing this file.
def list() -> builtins.list[OrganizationResponse]:
    """List the organizations the authenticated user belongs to.

    The wire-layer returns `OrganizationListResponse(organizations=[...], total=N)`;
    we unwrap because `.total` is redundant with `len(...)` for SDK callers.
    """
    response = list_organizations_orgs_get.sync(client=client())
    if not isinstance(response, OrganizationListResponse):
        raise RuntimeError(f"Unexpected response from orgs.list(): {response!r}")
    return response.organizations


def get(org_id: str) -> OrganizationResponse:
    """Fetch a single organization by ID."""
    response = get_organization_orgs_org_id_get.sync(client=client(), org_id=org_id)
    if not isinstance(response, OrganizationResponse):
        raise RuntimeError(f"Unexpected response from orgs.get({org_id!r}): {response!r}")
    return response
