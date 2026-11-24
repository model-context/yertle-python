"""Reads of public organizations, without a token. Imported as `yertle.public`.

    >>> import yertle
    >>> graph = yertle.public.graph("8f14e45f-...")
    >>> print(graph.org_name, graph.total_nodes)

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
no public route for an org's hierarchy or for its search, and a public read
returns less than a member's: no role, no invite settings.
"""

from __future__ import annotations

from yertle_client.api.public import (
    get_public_org_graph_public_orgs_org_id_graph_get,
    get_public_org_nodes_public_orgs_org_id_nodes_get,
    get_public_tree_document_public_orgs_org_id_nodes_node_id_tree_branch_get,
)
from yertle_client.models import NodeListResponse, NodeResponse, NodeTreeDocument, OrgGraphResponse

from yertle._client import anonymous_client
from yertle._ids import wire_org_id
from yertle._paging import PAGE_SIZE, all_nodes
from yertle.nodes import DEFAULT_BRANCH

__all__ = ["PARENT_CHILD", "get_node", "graph", "list_nodes"]

#: `GraphEdge.edge_type` for containment, as opposed to `"connection"`.
PARENT_CHILD = "parent_child"


def graph(org_id: str) -> OrgGraphResponse:
    """Fetch a public organization's whole graph: every node and every edge.

    Edges are of two kinds, told apart by `edge_type`. A `PARENT_CHILD` edge
    runs from a node to a node it contains; a `"connection"` edge is an arrow
    drawn between two nodes on a canvas. The containment edges are the same
    hierarchy that `yertle.nodes.tree()` returns for a member, as edges
    rather than as paths.

    The response also carries the org's name, which makes this the read for
    an anonymous caller who wants to know what an org is called.

        >>> graph = yertle.public.graph(org_id)
        >>> contains = [e for e in graph.edges if e.edge_type == yertle.public.PARENT_CHILD]

    Raises `ValueError` if `org_id` is not a UUID.
    """
    response = get_public_org_graph_public_orgs_org_id_graph_get.sync(
        client=anonymous_client(),
        org_id=wire_org_id(org_id),
    )
    if not isinstance(response, OrgGraphResponse):
        raise RuntimeError(f"Unexpected response from public.graph({org_id!r}): {response!r}")
    return response


def list_nodes(org_id: str) -> list[NodeResponse]:
    """List every node in a public organization.

    Pages are fetched and concatenated, exactly as `yertle.nodes.list()` does
    for a member.

        >>> for node in yertle.public.list_nodes(org_id):
        ...     print(node.title)

    Raises `ValueError` if `org_id` is not a UUID.
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

    Raises `ValueError` if `org_id` is not a UUID.
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
