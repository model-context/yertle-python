"""Nodes resource. Imported as `yertle.nodes`.

    >>> import yertle
    >>> for node in yertle.nodes.list(org_id="8f14e45f-..."):
    ...     print(node.title)
    >>> everything = yertle.nodes.list()      # every org you belong to

Module-as-namespace, following the shape `orgs.py` established.
"""

from __future__ import annotations

import builtins
from uuid import UUID

from yertle_client.api.directories import (
    get_all_orgs_hierarchy_orgs_all_hierarchy_get,
    get_org_hierarchy_orgs_org_id_hierarchy_get,
)
from yertle_client.api.nodes import (
    list_all_nodes_across_orgs_orgs_all_nodes_get,
    list_nodes_orgs_org_id_nodes_get,
)
from yertle_client.models import (
    HierarchyEntryResponse,
    HierarchyResponse,
    NodeListResponse,
    NodeResponse,
)

from yertle._client import client

__all__ = ["ALL_ORGS", "list", "tree"]

#: Sentinel for "every organization the caller belongs to" — the backend spells
#: it this way too, as the literal path segment in `/orgs/all/nodes`.
ALL_ORGS = "all"

# The endpoint's own default page size. Named because the loop below reasons
# about it, not because it is configurable.
_PAGE_SIZE = 50


# `list` shadows the builtin inside this module — annotations reference
# `builtins.list` explicitly, exactly as `orgs.py` does. The shadow is only
# visible when editing this file.
def list(org_id: str = ALL_ORGS) -> builtins.list[NodeResponse]:
    """List nodes in one organization, or across every org you belong to.

    Pages are fetched and concatenated here rather than handed to the caller.
    `/orgs/{id}/nodes` returns 50 at a time, and nobody wants page 1 of an
    architecture graph — they want the graph. This settles the pagination
    question left open in `docs/sdk/OVERVIEW.md`; if a lazy variant is ever
    needed, add `nodes.iter()` beside this rather than making every caller
    page by hand.

    Raises `ValueError` if `org_id` is neither `"all"` nor a UUID.
    """
    nodes: builtins.list[NodeResponse] = []
    offset = 0
    while True:
        page = _fetch_page(org_id, offset=offset)
        nodes.extend(page.nodes)
        # Stop on a short or empty page as well as on the reported total: a
        # total that never catches up would otherwise spin forever, and an
        # empty page means there is nothing left regardless of what it says.
        if not page.nodes or len(nodes) >= page.total:
            return nodes
        offset += len(page.nodes)


def _fetch_page(org_id: str, *, offset: int) -> NodeListResponse:
    """Fetch one page, picking the org-scoped or cross-org endpoint."""
    if org_id == ALL_ORGS:
        response = list_all_nodes_across_orgs_orgs_all_nodes_get.sync(
            client=client(),
            limit=_PAGE_SIZE,
            offset=offset,
        )
    else:
        # The generated signature types this as UUID even though sibling
        # endpoints take a plain str; convert rather than pass a str through a
        # mistyped parameter.
        response = list_nodes_orgs_org_id_nodes_get.sync(
            client=client(),
            org_id=UUID(org_id),
            limit=_PAGE_SIZE,
            offset=offset,
        )
    if not isinstance(response, NodeListResponse):
        raise RuntimeError(f"Unexpected response from nodes.list(): {response!r}")
    return response


def tree(org_id: str = ALL_ORGS) -> builtins.list[HierarchyEntryResponse]:
    """Return the containment hierarchy as a flat list of entries.

    Each entry carries the path of its *parent*, so a node's own path is
    `entry.path` joined with its title — that is how the backend models it and
    reshaping here would just move the join somewhere less obvious. Callers
    that want a nested structure build it from `path`; the CLI does exactly
    that in `cli/commands/nodes.py`.

    Unlike `list()` this endpoint does not paginate — it returns `entries` and
    `total` in one response — so there is no page loop to hide.

    Raises `ValueError` if `org_id` is neither `"all"` nor a UUID.
    """
    if org_id == ALL_ORGS:
        response = get_all_orgs_hierarchy_orgs_all_hierarchy_get.sync(client=client())
    else:
        response = get_org_hierarchy_orgs_org_id_hierarchy_get.sync(
            client=client(),
            org_id=UUID(org_id),
        )
    if not isinstance(response, HierarchyResponse):
        raise RuntimeError(f"Unexpected response from nodes.tree(): {response!r}")
    return response.entries
