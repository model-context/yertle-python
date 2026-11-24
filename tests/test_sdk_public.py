"""Tests for `yertle.public`, against captured `/public` responses."""

import copy
from typing import Any

import pytest
from yertle_client.errors import UnexpectedStatus

import yertle
from tests._public_api import CHECKOUT, LEDGER, ORG, PAYMENTS, ROOT, PublicAPI, fixture
from yertle._client import anonymous_client


def test_graph_reads_the_public_route_without_a_token(public_api: PublicAPI) -> None:
    public_api.serve(f"/public/orgs/{ORG}/graph", fixture("graph.json"))

    graph = yertle.public.graph(ORG)

    assert graph.org_name == "Example public org"
    assert {node.id for node in graph.nodes} == {ROOT, PAYMENTS, LEDGER, CHECKOUT}
    contains = {
        (edge.source, edge.target)
        for edge in graph.edges
        if edge.edge_type == yertle.public.PARENT_CHILD
    }
    assert contains == {(ROOT, PAYMENTS), (ROOT, CHECKOUT), (PAYMENTS, LEDGER)}
    (request,) = public_api.requests
    assert "authorization" not in request.headers


def test_list_nodes_returns_every_node(public_api: PublicAPI) -> None:
    public_api.serve(f"/public/orgs/{ORG}/nodes", fixture("nodes.json"))

    nodes = yertle.public.list_nodes(ORG)

    assert sorted(node.title for node in nodes) == ["Checkout API", "Ledger DB", "Payments", "Root"]
    (request,) = public_api.requests
    assert request.url.params["limit"] == "50"
    assert "authorization" not in request.headers


def test_list_nodes_concatenates_pages(public_api: PublicAPI) -> None:
    """The page loop is shared with `nodes.list()`; check it is wired to the public route."""
    full: Any = fixture("nodes.json")
    for offset in (0, 2):
        page = copy.deepcopy(full)
        page["nodes"] = full["nodes"][offset : offset + 2]
        page["offset"] = offset
        public_api.serve(f"/public/orgs/{ORG}/nodes?offset={offset}", page)

    nodes = yertle.public.list_nodes(ORG)

    assert len(nodes) == full["total"]
    assert [r.url.params["offset"] for r in public_api.requests] == ["0", "2"]


def test_get_node_returns_the_tree_document(public_api: PublicAPI) -> None:
    public_api.serve(
        f"/public/orgs/{ORG}/nodes/{PAYMENTS}/tree/main", fixture("tree_document.json")
    )

    doc = yertle.public.get_node(PAYMENTS, org_id=ORG)

    assert doc.state.node.title == "Payments"
    assert doc.status.org_id == ORG


def test_get_node_reads_the_branch_it_is_given(public_api: PublicAPI) -> None:
    public_api.serve(
        f"/public/orgs/{ORG}/nodes/{PAYMENTS}/tree/draft", fixture("tree_document.json")
    )

    yertle.public.get_node(PAYMENTS, org_id=ORG, branch="draft")

    assert public_api.requests[0].url.path.endswith("/tree/draft")


def test_a_private_or_missing_org_raises_404(public_api: PublicAPI) -> None:
    with pytest.raises(UnexpectedStatus) as excinfo:
        yertle.public.graph(ORG)
    assert excinfo.value.status_code == 404


def test_a_non_uuid_org_id_is_refused_before_a_request(public_api: PublicAPI) -> None:
    with pytest.raises(ValueError):
        yertle.public.graph("not-a-uuid")
    assert public_api.requests == []


def test_configure_points_public_reads_at_the_same_backend() -> None:
    yertle.configure(token="yrt_abc", api_url="http://localhost:9999")

    client = anonymous_client()
    assert client._base_url == "http://localhost:9999"  # pyright: ignore[reportPrivateUsage]
    assert not hasattr(client, "token")


def test_the_anonymous_client_is_built_from_resolved_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YERTLE_API_URL", "http://localhost:8000")

    client = anonymous_client()

    assert client._base_url == "http://localhost:8000"  # pyright: ignore[reportPrivateUsage]
    assert anonymous_client() is client
