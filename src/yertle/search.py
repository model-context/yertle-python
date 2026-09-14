"""Graph-aware retrieval. Imported as `yertle.search`.

    >>> import yertle
    >>> result = yertle.search.retrieve("payment path", org_id="8f14e45f-...")
    >>> for match in result.matches:
    ...     print(match.score, match.title)

Ranked node matches for a natural-language query, optionally expanded into the
surrounding subgraph. Distinct from a future `yertle.nodes.list(...)` filter:
this ranks by semantic similarity, it does not filter by exact field values.
"""

from __future__ import annotations

from uuid import UUID

from yertle_client.api.search import (
    retrieve_subgraph_orgs_org_id_search_retrieve_post as _retrieve,
)
from yertle_client.models import (
    RetrievalScopeRequest,
    RetrievalScopeRequestTagFiltersType0,
    RetrieveRequest,
    RetrieveRequestExpansionDepthType0,
    RetrieveResponse,
)
from yertle_client.types import UNSET, Unset

from yertle._client import client

__all__ = ["Expansion", "retrieve"]

#: How far to walk out from each match. Re-exported so callers need not import
#: from the generated package to name a depth.
Expansion = RetrieveRequestExpansionDepthType0


def retrieve(
    query: str,
    *,
    org_id: str,
    top_k: int = 5,
    expansion: Expansion | None = None,
    root_node_id: str | None = None,
    tag_filters: dict[str, str] | None = None,
    directory_prefix: str | None = None,
    include_text: bool = False,
) -> RetrieveResponse:
    """Rank nodes against `query`, optionally expanding into their neighbours.

    `expansion=None` sends no depth at all and lets the server apply its own
    default, rather than this client asserting one. The scope arguments narrow
    the candidate set *before* ranking, so they cut noise rather than
    re-ordering it.

    `org_id` is required and cannot be `"all"` — retrieval is scoped to a
    single organization's graph.
    """
    if org_id == "all":
        raise ValueError("search.retrieve() needs a specific org_id, not 'all'.")

    scope: RetrievalScopeRequest | Unset = UNSET
    if root_node_id or tag_filters or directory_prefix:
        scope = RetrievalScopeRequest(
            root_node_id=root_node_id or UNSET,
            directory_prefix=directory_prefix or UNSET,
            tag_filters=(
                RetrievalScopeRequestTagFiltersType0.from_dict(tag_filters)
                if tag_filters
                else UNSET
            ),
        )

    response = _retrieve.sync(
        client=client(),
        org_id=UUID(org_id),
        body=RetrieveRequest(
            query=query,
            top_k=top_k,
            expansion_depth=expansion if expansion is not None else UNSET,
            scope=scope,
            include_raw_text=include_text,
        ),
    )
    if not isinstance(response, RetrieveResponse):
        raise RuntimeError(f"Unexpected response from search.retrieve(): {response!r}")
    return response
