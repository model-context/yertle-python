"""Reads of public organizations, without a token. Imported as `yertle.public`.

    >>> import yertle
    >>> org = yertle.public.get_org("8f14e45f-...")
    >>> print(org.name, org.node_count)

An organization marked public can be read by anyone, through the backend's
`/public/orgs/...` routes. Everything here goes through an anonymous client
that sends no token, so it works before `yertle login` — and it only ever
reaches those routes, so it cannot read a private org or write anything.

A private organization and one that does not exist both answer 404, so a
caller cannot tell them apart; that is the backend's choice, made so that
anonymous callers cannot probe which org ids exist. The 404 surfaces as
`yertle_client.errors.UnexpectedStatus`.

Kept as its own module, rather than as a `public=True` flag on `yertle.orgs`
and `yertle.nodes`, because the two surfaces are not the same shape. There is
no public route for an org's search, and a public read can return less than a
member's: `get_org()` has no role or invite settings.
"""

from __future__ import annotations

from yertle_client.api.public import (
    get_public_node_location_public_nodes_node_id_get,
    get_public_org_hierarchy_public_orgs_org_id_hierarchy_get,
    get_public_org_nodes_public_orgs_org_id_nodes_get,
    get_public_org_public_orgs_org_id_get,
    get_public_tree_document_public_orgs_org_id_nodes_node_id_tree_branch_get,
)
from yertle_client.models import (
    HierarchyEntryResponse,
    HierarchyResponse,
    NodeListResponse,
    NodeLocationResponse,
    NodeResponse,
    NodeTreeDocument,
    PublicOrganizationResponse,
)

from yertle._client import anonymous_client
from yertle._ids import full_id, wire_org_id
from yertle._paging import PAGE_SIZE, all_nodes
from yertle.nodes import DEFAULT_BRANCH

__all__ = ["get_node", "get_org", "hierarchy", "list_nodes", "locate"]


def get_org(org_id: str) -> PublicOrganizationResponse:
    """Fetch a public organization's details: name, description and counts.

    The public counterpart of `yertle.orgs.get()`, and deliberately smaller.
    The backend returns an allowlist (`id`, `name`, `description`,
    `member_count`, `node_count`, `created_at`) and none of what only a
    member should see: no role, no invite settings, no root node.

        >>> org = yertle.public.get_org(org_id)
        >>> print(f"{org.name}: {org.node_count} nodes, {org.member_count} members")

    Raises `ValueError` if `org_id` is neither a UUID nor a short id.
    """
    response = get_public_org_public_orgs_org_id_get.sync(
        client=anonymous_client(),
        org_id=wire_org_id(org_id),
    )
    if not isinstance(response, PublicOrganizationResponse):
        raise RuntimeError(f"Unexpected response from public.get_org({org_id!r}): {response!r}")
    return response


def hierarchy(org_id: str) -> list[HierarchyEntryResponse]:
    """Return a public organization's containment hierarchy as a flat list of entries.

    The public counterpart of `yertle.nodes.tree()`, and the same response:
    the backend runs one query for both routes, so anything that renders a
    member's hierarchy renders this. Each entry carries the path of its
    *parent*; a node with two parents appears once under each.

        >>> for entry in yertle.public.hierarchy(org_id):
        ...     print(entry.depth, entry.path, entry.title)

    Raises `ValueError` if `org_id` is neither a UUID nor a short id.
    """
    response = get_public_org_hierarchy_public_orgs_org_id_hierarchy_get.sync(
        client=anonymous_client(),
        org_id=wire_org_id(org_id),
    )
    if not isinstance(response, HierarchyResponse):
        raise RuntimeError(f"Unexpected response from public.hierarchy({org_id!r}): {response!r}")
    return response.entries


def list_nodes(org_id: str) -> list[NodeResponse]:
    """List every node in a public organization.

    Pages are fetched and concatenated, exactly as `yertle.nodes.list()` does
    for a member.

        >>> for node in yertle.public.list_nodes(org_id):
        ...     print(node.title)

    Raises `ValueError` if `org_id` is neither a UUID nor a short id.
    """
    wire_id = wire_org_id(org_id)

    def fetch_page(offset: int) -> NodeListResponse:
        response = get_public_org_nodes_public_orgs_org_id_nodes_get.sync(
            client=anonymous_client(),
            org_id=wire_id,
            limit=PAGE_SIZE,
            offset=offset,
        )
        if not isinstance(response, NodeListResponse):
            raise RuntimeError(f"Unexpected response from public.list_nodes(): {response!r}")
        return response

    return all_nodes(fetch_page)


def get_node(node_id: str, *, org_id: str, branch: str = DEFAULT_BRANCH) -> NodeTreeDocument:
    """Fetch a node's document in a public organization, at `branch`.

    The same document `yertle.nodes.get()` returns to a member, so anything
    that renders one renders this. It is read-only in practice: pushing needs
    a token, and membership.

        >>> doc = yertle.public.get_node(node_id, org_id=org_id)
        >>> print(doc.state.node.title)

    Raises `ValueError` if `org_id` is neither a UUID nor a short id.
    """
    response = get_public_tree_document_public_orgs_org_id_nodes_node_id_tree_branch_get.sync(
        client=anonymous_client(),
        org_id=wire_org_id(org_id),
        node_id=node_id,
        branch=branch,
    )
    if not isinstance(response, NodeTreeDocument):
        raise RuntimeError(f"Unexpected response from public.get_node({node_id!r}): {response!r}")
    return response


def locate(node_id: str) -> NodeLocationResponse:
    """Find which public organization a node belongs to, from the node's id alone.

    The anonymous counterpart of `yertle.nodes.locate()`, and the same
    response. It answers only for a node in a public organization: a private
    one, and one that does not exist, are both a 404.

        >>> where = yertle.public.locate(node_id)
        >>> doc = yertle.public.get_node(node_id, org_id=where.org_id)

    Full ids only: the backend matches short ids for members alone, so that
    an anonymous caller cannot probe for nodes, and answers one here with a
    404 indistinguishable from "no such node".

    Raises `ValueError` if `node_id` is not a full UUID.
    """
    response = get_public_node_location_public_nodes_node_id_get.sync(
        client=anonymous_client(),
        node_id=full_id(node_id),
    )
    if not isinstance(response, NodeLocationResponse):
        raise RuntimeError(f"Unexpected response from public.locate({node_id!r}): {response!r}")
    return response
