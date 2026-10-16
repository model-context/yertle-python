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
    create_organization_orgs_post,
    get_organization_orgs_org_id_get,
    list_organizations_orgs_get,
    update_organization_orgs_org_id_patch,
)
from yertle_client.models import (
    CreateOrganizationRequest,
    OrganizationListResponse,
    OrganizationResponse,
    UpdateOrganizationRequest,
)
from yertle_client.types import UNSET

from yertle._client import client

__all__ = ["create", "get", "list", "update"]


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


def create(name: str, *, description: str | None = None) -> OrganizationResponse:
    """Create an organization, returning it as the backend stored it.

    The caller becomes its owner. Two side effects are worth knowing about,
    because neither is visible in the request: the backend auto-creates a
    **Root node** for the new org, and two persistent invite links (viewer
    and editor). The root node is the one you attach everything else to, and
    its id comes back as `root_node_id`.

    `description` is sent only when given, so the backend's own default (an
    empty string) applies otherwise.
    """
    response = create_organization_orgs_post.sync(
        client=client(),
        body=CreateOrganizationRequest(
            name=name,
            description=description if description is not None else UNSET,
        ),
    )
    if not isinstance(response, OrganizationResponse):
        raise RuntimeError(f"Unexpected response from orgs.create({name!r}): {response!r}")
    return response


def update(
    org_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
) -> OrganizationResponse:
    """Change an organization's name or description, returning it as stored.

    A genuine PATCH: a field you do not pass is not sent, so the backend
    leaves it alone. That is what lets you rename an organization without
    also having to restate its description.

    Passing an empty string for `description` is therefore different from
    omitting it — the empty string clears the description, omission keeps it.
    """
    response = update_organization_orgs_org_id_patch.sync(
        client=client(),
        org_id=org_id,
        body=UpdateOrganizationRequest(
            name=name if name is not None else UNSET,
            description=description if description is not None else UNSET,
        ),
    )
    if not isinstance(response, OrganizationResponse):
        raise RuntimeError(f"Unexpected response from orgs.update({org_id!r}): {response!r}")
    return response
