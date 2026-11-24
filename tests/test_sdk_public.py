"""Tests for `yertle.public`, against captured `/public` responses."""

import copy
from typing import Any

import pytest
from yertle_client.errors import UnexpectedStatus

import yertle
from tests._public_api import (
    AUTH,
    CHECKOUT,
    LEDGER,
    ORG,
    PAYMENTS,
    ROOT,
    SCRATCHPAD,
    PublicAPI,
    fixture,
)
from yertle._client import anonymous_client


def test_hierarchy_reads_the_public_route_without_a_token(public_api: PublicAPI) -> None:
    public_api.serve(f"/public/orgs/{ORG}/hierarchy", fixture("hierarchy.json"))

    entries = yertle.public.hierarchy(ORG)

    assert {(entry.path, entry.title, entry.node_id) for entry in entries} == {
        ("/", "Root", ROOT),
        ("/", "Scratchpad", SCRATCHPAD),
        ("/Root", "Checkout API", CHECKOUT),
        ("/Root", "Payments", PAYMENTS),
        ("/Root", "Auth / Sessions", AUTH),
        ("/Root/Checkout API", "Ledger DB", LEDGER),
        ("/Root/Payments", "Ledger DB", LEDGER),
    }
    (request,) = public_api.requests
    assert request.url.path == f"/public/orgs/{ORG}/hierarchy"
    assert "authorization" not in request.headers


def test_hierarchy_is_the_member_response_of_the_same_org(public_api: PublicAPI) -> None:
    """Captured from one org: anonymously, and by its owner. The routes share a query."""
    public_api.serve(f"/public/orgs/{ORG}/hierarchy", fixture("hierarchy.json"))

    entries = yertle.public.hierarchy(ORG)

    member: Any = fixture("hierarchy_member.json")
    assert [entry.to_dict() for entry in entries] == member["entries"]


def test_list_nodes_returns_every_node(public_api: PublicAPI) -> None:
    public_api.serve(f"/public/orgs/{ORG}/nodes", fixture("nodes.json"))

    nodes = yertle.public.list_nodes(ORG)

    assert sorted(node.title for node in nodes) == [
        "Auth / Sessions",
        "Checkout API",
        "Ledger DB",
        "Payments",
        "Root",
        "Scratchpad",
    ]
    (request,) = public_api.requests
    assert request.url.params["limit"] == "50"
    assert "authorization" not in request.headers


def test_get_org_returns_the_public_allowlist(public_api: PublicAPI) -> None:
    public_api.serve(f"/public/orgs/{ORG}", fixture("org.json"))

    org = yertle.public.get_org(ORG)

    assert (org.id, org.name) == (ORG, "Example public org")
    assert org.description == "A public org used by the tests."
    assert (org.member_count, org.node_count) == (1, 6)
    (request,) = public_api.requests
    assert "authorization" not in request.headers


def test_a_private_org_is_indistinguishable_from_a_missing_one(public_api: PublicAPI) -> None:
    """Both captures are real: one before the org was published, one for a random id."""
    assert fixture("not_found_private_org.json") == fixture("not_found_org.json")
    public_api.serve(f"/public/orgs/{ORG}", fixture("not_found_private_org.json"), status=404)

    with pytest.raises(UnexpectedStatus) as excinfo:
        yertle.public.get_org(ORG)
    assert excinfo.value.status_code == 404


def test_list_nodes_concatenates_pages(public_api: PublicAPI) -> None:
    """The page loop is shared with `nodes.list()`; check it is wired to the public route."""
    full: Any = fixture("nodes.json")
    for offset in range(0, full["total"], 2):
        page = copy.deepcopy(full)
        page["nodes"] = full["nodes"][offset : offset + 2]
        page["offset"] = offset
        public_api.serve(f"/public/orgs/{ORG}/nodes?offset={offset}", page)

    nodes = yertle.public.list_nodes(ORG)

    assert len(nodes) == full["total"]
    assert [r.url.params["offset"] for r in public_api.requests] == ["0", "2", "4"]


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
        yertle.public.hierarchy(ORG)
    assert excinfo.value.status_code == 404
    (request,) = public_api.requests
    assert "authorization" not in request.headers


def test_a_non_uuid_org_id_is_refused_before_a_request(public_api: PublicAPI) -> None:
    with pytest.raises(ValueError):
        yertle.public.hierarchy("not-a-uuid")
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


def test_locate_reads_the_public_route_without_a_token(public_api: PublicAPI) -> None:
    public_api.serve(f"/public/nodes/{PAYMENTS}", fixture("node_location.json"))

    where = yertle.public.locate(PAYMENTS)

    assert (where.node_id, where.org_id, where.org_name) == (PAYMENTS, ORG, "Example public org")
    assert where.title == "Payments"
    (request,) = public_api.requests
    assert request.url.path == f"/public/nodes/{PAYMENTS}"
    assert "authorization" not in request.headers


def test_locate_is_the_member_response_for_a_public_node() -> None:
    """Captured for one node: anonymously, and by its org's owner."""
    assert fixture("node_location.json") == fixture("node_location_member.json")


def test_locate_of_a_private_or_missing_node_raises_404(public_api: PublicAPI) -> None:
    public_api.serve(
        f"/public/nodes/{PAYMENTS}", fixture("not_found_node_location.json"), status=404
    )

    with pytest.raises(UnexpectedStatus) as excinfo:
        yertle.public.locate(PAYMENTS)
    assert excinfo.value.status_code == 404


def test_locate_refuses_a_non_uuid_before_a_request(public_api: PublicAPI) -> None:
    with pytest.raises(ValueError):
        yertle.public.locate(PAYMENTS[:8])
    assert public_api.requests == []


def test_locate_raises_on_an_unexpected_response(public_api: PublicAPI) -> None:
    public_api.serve(f"/public/nodes/{PAYMENTS}", {"detail": []}, status=422)

    with pytest.raises(RuntimeError, match=r"public\.locate"):
        yertle.public.locate(PAYMENTS)
