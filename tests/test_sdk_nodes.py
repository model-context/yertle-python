"""Tests for `yertle.nodes`.

Pagination is the interesting part: the facade concatenates pages so callers
never see them, which means the loop's stopping conditions are the thing most
worth pinning down.
"""

import datetime
from unittest.mock import patch

import pytest
from yertle_client.models import NodeListResponse, NodeResponse

import yertle


def _node(node_id: str) -> NodeResponse:
    now = datetime.datetime(2026, 9, 2, tzinfo=datetime.UTC)
    return NodeResponse(
        id=node_id,
        title=f"Node {node_id}",
        description="",
        org_id="8f14e45f-ceea-467a-9575-28db8d0dc4db",
        public_id=node_id,
        created_by="someone",
        created_at=now,
    )


def _page(ids: list[str], *, total: int, offset: int = 0) -> NodeListResponse:
    return NodeListResponse(
        nodes=[_node(i) for i in ids],
        total=total,
        limit=50,
        offset=offset,
    )


ORG = "8f14e45f-ceea-467a-9575-28db8d0dc4db"
_ORG_SCOPED = "yertle.nodes.list_nodes_orgs_org_id_nodes_get.sync"
_CROSS_ORG = "yertle.nodes.list_all_nodes_across_orgs_orgs_all_nodes_get.sync"


@patch(_ORG_SCOPED, return_value=_page(["a", "b"], total=2))
@patch("yertle._client.get_client", return_value=object())
def test_list_returns_a_single_page(_get_client, _sync) -> None:
    nodes = yertle.nodes.list(ORG)
    assert [n.id for n in nodes] == ["a", "b"]


@patch("yertle._client.get_client", return_value=object())
def test_list_concatenates_every_page(_get_client) -> None:
    """The caller gets the graph, not page 1."""
    pages = [
        _page(["a", "b"], total=5, offset=0),
        _page(["c", "d"], total=5, offset=2),
        _page(["e"], total=5, offset=4),
    ]
    with patch(_ORG_SCOPED, side_effect=pages) as sync:
        nodes = yertle.nodes.list(ORG)

    assert [n.id for n in nodes] == ["a", "b", "c", "d", "e"]
    assert [call.kwargs["offset"] for call in sync.call_args_list] == [0, 2, 4]


@patch("yertle._client.get_client", return_value=object())
def test_list_stops_on_an_empty_page_even_if_total_disagrees(_get_client) -> None:
    """A total that never catches up must not spin forever."""
    pages = [_page(["a"], total=99), _page([], total=99)]
    with patch(_ORG_SCOPED, side_effect=pages):
        nodes = yertle.nodes.list(ORG)

    assert [n.id for n in nodes] == ["a"]


@patch(_CROSS_ORG, return_value=_page(["a"], total=1))
@patch("yertle._client.get_client", return_value=object())
def test_list_defaults_to_the_cross_org_endpoint(_get_client, sync) -> None:
    nodes = yertle.nodes.list()
    assert len(nodes) == 1
    assert "org_id" not in sync.call_args.kwargs


@patch("yertle._client.get_client", return_value=object())
def test_list_rejects_a_non_uuid_org(_get_client) -> None:
    with pytest.raises(ValueError, match=r"badly formed|invalid"):
        yertle.nodes.list("not-a-uuid")


@patch(_ORG_SCOPED, return_value=None)
@patch("yertle._client.get_client", return_value=object())
def test_list_raises_on_an_unexpected_response(_get_client, _sync) -> None:
    with pytest.raises(RuntimeError, match="Unexpected response"):
        yertle.nodes.list(ORG)
