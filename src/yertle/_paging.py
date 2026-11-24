"""Collecting every page of a paginated node listing.

Shared by `yertle.nodes` and `yertle.public`, whose node listings page the
same way over different routes.
"""

from __future__ import annotations

from collections.abc import Callable

from yertle_client.models import NodeListResponse, NodeResponse

__all__ = ["PAGE_SIZE", "all_nodes"]

# The endpoints' own default page size. Named because the loop below reasons
# about it, not because it is configurable.
PAGE_SIZE = 50


def all_nodes(fetch_page: Callable[[int], NodeListResponse]) -> list[NodeResponse]:
    """Call `fetch_page(offset)` until the listing is exhausted.

    Stops on a short or empty page as well as on the reported total: a total
    that never catches up would otherwise spin forever, and an empty page means
    there is nothing left regardless of what it says.
    """
    nodes: list[NodeResponse] = []
    offset = 0
    while True:
        page = fetch_page(offset)
        nodes.extend(page.nodes)
        if not page.nodes or len(nodes) >= page.total:
            return nodes
        offset += len(page.nodes)
