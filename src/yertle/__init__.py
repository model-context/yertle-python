"""yertle — Python SDK for the Yertle architecture-graph platform.

MVP facade: re-exports a small set of read endpoints from the underlying
`yertle_client` wire layer as plain top-level functions, with a lazy
default `AuthenticatedClient` that resolves credentials the same way
the CLI does (`$YERTLE_TOKEN` env > `~/.yertle/config.json` > error).

    >>> import yertle
    >>> for org in yertle.list_orgs():
    ...     print(org.name)

The wire layer is still available for users who want it:

    >>> from yertle_client.api.organizations import list_organizations_orgs_get
    >>> from yertle_client import AuthenticatedClient

Scope is intentionally tiny. The point of this slice is to prove the
default-client + facade shape; the wider surface (nodes, search, tree,
canvas, branches) lands once we know what feels right in real use.
"""

from __future__ import annotations

from yertle_client.api.organizations import (
    get_organization_orgs_org_id_get,
    list_organizations_orgs_get,
)
from yertle_client.client import AuthenticatedClient
from yertle_client.models import OrganizationListResponse, OrganizationResponse

# TODO(consolidation): when shared/auth.py lands (the third real consumer
# is now the SDK), have cli/auth, mcp/server, and yertle/__init__ all
# import from there. Today this single import is the only thing tying
# the SDK to the CLI subpackage.
from yertle.cli.auth import get_client

__version__ = "0.0.1"
__all__ = ["AuthenticatedClient", "client", "get_client", "get_org", "list_orgs"]


_default_client: AuthenticatedClient | None = None


def client() -> AuthenticatedClient:
    """Return the cached default `AuthenticatedClient`, building it on first call.

    Resolution: `$YERTLE_TOKEN` env > config file > raise `AuthError`.
    Override the URL via `$YERTLE_API_URL` or the config file. Same as the CLI.
    """
    global _default_client  # noqa: PLW0603 — module-level lazy singleton is intentional
    if _default_client is None:
        _default_client = get_client()
    return _default_client


def list_orgs() -> list[OrganizationResponse]:
    """List the organizations the authenticated user belongs to.

    The wire-layer return type is `OrganizationListResponse(organizations=[...],
    total=N)`; the facade unwraps and returns the list directly because the
    `.total` is redundant with `len(...)` for an SDK caller.
    """
    response = list_organizations_orgs_get.sync(client=client())
    if not isinstance(response, OrganizationListResponse):
        raise RuntimeError(f"Unexpected response from list_orgs: {response!r}")
    return response.organizations


def get_org(org_id: str) -> OrganizationResponse:
    """Fetch a single organization by ID."""
    response = get_organization_orgs_org_id_get.sync(client=client(), org_id=org_id)
    if not isinstance(response, OrganizationResponse):
        raise RuntimeError(f"Unexpected response from get_org({org_id!r}): {response!r}")
    return response
