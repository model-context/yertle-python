"""Short ids for orgs and nodes: `yertle nodes show ab7bd00e`, `yertle orgs use dc047318` (#60).

Served over an `httpx.MockTransport` from responses captured against a real
backend (see `tests/_short_ids.py`), so the real bindings build each URL and
parse each body. The mock does not resolve prefixes itself: each test serves
the path the CLI should request, with what the backend answered there.
"""

import json

import pytest
from typer.testing import CliRunner

from tests._output import plain
from tests._public_api import PublicAPI, install_member
from tests._public_api import fixture as public_fixture
from tests._short_ids import (
    FULL_NODE,
    FULL_ORG,
    ROOT_NODE,
    SHORT_NODE,
    SHORT_ORG,
    TWIN_NODE,
    UNMATCHED_NODE,
    UNMATCHED_ORG,
    fixture,
)
from yertle.cli._context import PUBLIC_FALLBACK_HINT
from yertle.cli.main import app
from yertle.shared import auth

runner = CliRunner()

LOOKUP = f"/nodes/{SHORT_NODE}"
TREE = f"/orgs/{FULL_ORG}/nodes/{FULL_NODE}/tree/main"
PUBLIC_TREE = f"/public{TREE}"
# Where a short node id is resolved inside a named public org.
PUBLIC_SHORT_TREE = f"/public/orgs/{SHORT_ORG}/nodes/{SHORT_NODE}/tree/main"


@pytest.fixture
def member(public_api: PublicAPI, token: str) -> PublicAPI:
    install_member(public_api, token)
    return public_api


def _requests(api: PublicAPI) -> list[tuple[str, bool]]:
    """Each request's path, and whether a token went with it."""
    return [(r.url.path, "authorization" in r.headers) for r in api.requests]


# --- Signed in, a member ----------------------------------------------------


def test_a_short_node_id_is_looked_up_then_read_by_its_full_id(member: PublicAPI) -> None:
    member.serve(LOOKUP, fixture("node_location.json"))
    member.serve(TREE, fixture("tree_document.json"))

    result = runner.invoke(app, ["nodes", "show", SHORT_NODE])

    assert result.exit_code == 0, result.output
    assert "Payments API" in result.output
    # The header names the node by the id the backend answered with.
    assert FULL_NODE in result.output
    assert _requests(member) == [(LOOKUP, True), (TREE, True)]


def test_a_short_org_is_checked_against_the_node(member: PublicAPI) -> None:
    member.serve(LOOKUP, fixture("node_location.json"))
    member.serve(TREE, fixture("tree_document.json"))

    result = runner.invoke(app, ["nodes", "show", SHORT_NODE, "--org", SHORT_ORG])

    assert result.exit_code == 0, result.output
    assert _requests(member) == [(LOOKUP, True), (TREE, True)]


def test_a_short_org_that_is_not_the_nodes_names_both(member: PublicAPI) -> None:
    member.serve(LOOKUP, fixture("node_location.json"))

    result = runner.invoke(app, ["nodes", "show", SHORT_NODE, "--org", UNMATCHED_ORG])

    assert result.exit_code == 1
    out = plain(result.output)
    assert f"is in organization {FULL_ORG}" in out
    assert f"not {UNMATCHED_ORG}, which came from --org" in out
    assert _requests(member) == [(LOOKUP, True)]


def test_an_ambiguous_lookup_lists_the_candidates_git_style(member: PublicAPI) -> None:
    member.serve(LOOKUP, fixture("ambiguous_node_location.json"), status=409)

    result = runner.invoke(app, ["nodes", "show", SHORT_NODE])

    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert lines[:3] == [
        f"Short ID '{SHORT_NODE}' is ambiguous: it matches more than one node.",
        "  Use more characters, or the full ID.",
        "  It matches:",
    ]
    assert lines[3].startswith(f"    {TWIN_NODE} (untitled")
    assert lines[4].startswith(f"    {FULL_NODE} (Payments API")
    # The cause is the id, never the backend's address.
    assert "API error from" not in result.output
    assert _requests(member) == [(LOOKUP, True)]


def test_an_ambiguous_org_prefix_has_no_candidates_to_list(member: PublicAPI) -> None:
    """The path middleware runs before auth, so its 409 names no ids."""
    member.serve(f"/orgs/{SHORT_ORG}/nodes", fixture("ambiguous_org.json"), status=409)

    result = runner.invoke(app, ["nodes", "list", "--org", SHORT_ORG])

    assert result.exit_code == 1
    assert result.output.splitlines() == [
        f"Short ID '{SHORT_ORG}' is ambiguous: it matches more than one organization.",
        "  Use more characters, or the full ID.",
    ]


def test_a_short_org_goes_on_the_wire_as_typed(member: PublicAPI) -> None:
    """Org ids only ever go in paths, where the backend resolves them."""
    member.serve(f"/orgs/{SHORT_ORG}/hierarchy", public_fixture("hierarchy_member.json"))

    result = runner.invoke(app, ["nodes", "tree", "--org", SHORT_ORG.upper()])

    assert result.exit_code == 0, result.output
    assert _requests(member) == [(f"/orgs/{SHORT_ORG}/hierarchy", True)]


# --- Without a token --------------------------------------------------------


def test_anonymous_a_short_node_id_needs_an_org(public_api: PublicAPI) -> None:
    """The anonymous lookup takes full ids only, so it is not tried."""
    result = runner.invoke(app, ["nodes", "show", SHORT_NODE])

    assert result.exit_code == 1
    out = plain(result.output)
    assert "Without a token, a short node id needs its organization." in out
    assert "--org" in out
    assert public_api.requests == []


def test_anonymous_a_short_node_id_resolves_in_the_named_org(
    public_api: PublicAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    public_api.serve(PUBLIC_SHORT_TREE, fixture("tree_document.json"))
    public_api.serve(PUBLIC_TREE, fixture("tree_document.json"))
    monkeypatch.setenv("YERTLE_ORG", SHORT_ORG)

    result = runner.invoke(app, ["nodes", "show", SHORT_NODE])

    assert result.exit_code == 0, result.output
    assert "Payments API" in result.output
    assert _requests(public_api) == [(PUBLIC_SHORT_TREE, False), (PUBLIC_TREE, False)]


def test_anonymous_an_ambiguous_node_is_explained(public_api: PublicAPI) -> None:
    public_api.serve(PUBLIC_SHORT_TREE, fixture("ambiguous_public_node.json"), status=409)

    result = runner.invoke(app, ["nodes", "show", SHORT_NODE, "--org", SHORT_ORG])

    assert result.exit_code == 1
    assert f"Short ID '{SHORT_NODE}' is ambiguous" in result.output


def test_anonymous_an_unmatched_node_is_the_public_not_found(public_api: PublicAPI) -> None:
    path = f"/public/orgs/{SHORT_ORG}/nodes/{UNMATCHED_NODE}/tree/main"
    public_api.serve(path, fixture("unmatched_public_tree.json"), status=404)

    result = runner.invoke(app, ["nodes", "show", UNMATCHED_NODE, "--org", SHORT_ORG])

    assert result.exit_code == 1
    assert "or not a public organization" in plain(result.output)


# --- Signed in, not a member ------------------------------------------------


def test_a_non_member_is_told_short_ids_match_only_their_orgs(member: PublicAPI) -> None:
    member.serve(LOOKUP, fixture("nonmember_locate_short.json"), status=404)

    result = runner.invoke(app, ["nodes", "show", SHORT_NODE])

    assert result.exit_code == 1
    out = plain(result.output)
    assert "Node not found" in out
    assert "A short id matches only nodes in organizations you belong to." in out
    assert _requests(member) == [(LOOKUP, True)]


def test_a_non_member_resolves_a_short_id_in_a_named_public_org(member: PublicAPI) -> None:
    """Lookup 404s; the named org's public route resolves it; the read falls back (#70)."""
    member.serve(LOOKUP, fixture("nonmember_locate_short.json"), status=404)
    member.serve(PUBLIC_SHORT_TREE, fixture("tree_document.json"))
    member.serve(TREE, public_fixture("forbidden_org_route.json"), status=403)
    member.serve(PUBLIC_TREE, fixture("tree_document.json"))

    result = runner.invoke(app, ["nodes", "show", SHORT_NODE, "--org", SHORT_ORG])

    assert result.exit_code == 0, result.output
    assert "Payments API" in result.stdout
    assert PUBLIC_FALLBACK_HINT in plain(result.stderr)
    assert _requests(member) == [
        (LOOKUP, True),
        (PUBLIC_SHORT_TREE, False),
        (TREE, True),
        (PUBLIC_TREE, False),
    ]


def test_a_short_id_found_nowhere_is_the_lookups_404(member: PublicAPI) -> None:
    """Not in your orgs, not in the named public org: the lookup's answer stands."""
    lookup = f"/nodes/{UNMATCHED_NODE}"
    public = f"/public/orgs/{SHORT_ORG}/nodes/{UNMATCHED_NODE}/tree/main"
    member.serve(lookup, fixture("unmatched_node_location.json"), status=404)
    member.serve(public, fixture("unmatched_public_tree.json"), status=404)

    result = runner.invoke(app, ["nodes", "show", UNMATCHED_NODE, "--org", SHORT_ORG])

    assert result.exit_code == 1
    out = plain(result.output)
    assert "404 from the API. Node not found" in out
    assert "not a public organization" not in out
    assert _requests(member) == [(lookup, True), (public, False)]


def test_a_failing_public_resolution_is_reported_as_itself(member: PublicAPI) -> None:
    member.serve(LOOKUP, fixture("nonmember_locate_short.json"), status=404)
    member.serve(PUBLIC_SHORT_TREE, {"detail": "Internal Server Error"}, status=500)

    result = runner.invoke(app, ["nodes", "show", SHORT_NODE, "--org", SHORT_ORG])

    assert result.exit_code == 1
    assert "500 from the API" in plain(result.output)


# --- orgs use ---------------------------------------------------------------


def _stored_org() -> str | None:
    return auth.configured_org()


def test_orgs_use_stores_the_full_id_never_the_prefix(member: PublicAPI) -> None:
    member.serve(f"/orgs/{SHORT_ORG}", fixture("org_member.json"))

    result = runner.invoke(app, ["orgs", "use", SHORT_ORG])

    assert result.exit_code == 0, result.output
    assert _stored_org() == FULL_ORG
    assert f"set to {FULL_ORG} (Short ID demo org)" in plain(result.output)


def test_orgs_use_resolves_a_public_org_for_a_non_member(member: PublicAPI) -> None:
    member.serve(f"/orgs/{SHORT_ORG}", public_fixture("forbidden_org.json"), status=403)
    member.serve(f"/public/orgs/{SHORT_ORG}", fixture("org_public.json"))

    result = runner.invoke(app, ["orgs", "use", SHORT_ORG])

    assert result.exit_code == 0, result.output
    assert _stored_org() == FULL_ORG


def test_orgs_use_resolves_without_a_token(public_api: PublicAPI) -> None:
    public_api.serve(f"/public/orgs/{SHORT_ORG}", fixture("org_public.json"))

    result = runner.invoke(app, ["orgs", "use", SHORT_ORG])

    assert result.exit_code == 0, result.output
    assert _stored_org() == FULL_ORG
    assert _requests(public_api) == [(f"/public/orgs/{SHORT_ORG}", False)]


@pytest.mark.parametrize(
    ("org", "status", "body", "says"),
    [
        (SHORT_ORG, 409, "ambiguous_org.json", f"Short ID '{SHORT_ORG}' is ambiguous"),
        (UNMATCHED_ORG, 404, "unmatched_org.json", "Organization not found"),
    ],
)
def test_orgs_use_saves_nothing_it_cannot_resolve(
    member: PublicAPI, org: str, status: int, body: str, says: str
) -> None:
    member.serve(f"/orgs/{org}", fixture(body), status=status)

    result = runner.invoke(app, ["orgs", "use", org])

    assert result.exit_code == 1
    assert says in plain(result.output)
    assert _stored_org() is None


def test_orgs_use_with_a_full_id_still_makes_no_request(member: PublicAPI) -> None:
    result = runner.invoke(app, ["orgs", "use", FULL_ORG])

    assert result.exit_code == 0, result.output
    assert _stored_org() == FULL_ORG
    assert member.requests == []


# --- search --scope-root ----------------------------------------------------


def test_a_short_scope_root_is_resolved_before_it_goes_in_the_body(member: PublicAPI) -> None:
    """The backend resolves ids in paths only; a short one in the body is a 400."""
    branches = f"/orgs/{FULL_ORG}/nodes/{SHORT_NODE}/branches"
    retrieve = f"/orgs/{FULL_ORG}/search/retrieve"
    member.serve(branches, fixture("branches.json"))
    member.serve(retrieve, fixture("search_scoped.json"))

    result = runner.invoke(
        app, ["nodes", "search", "payments", "--org", FULL_ORG, "--scope-root", SHORT_NODE]
    )

    assert result.exit_code == 0, result.output
    assert [path for path, _ in _requests(member)] == [branches, retrieve]
    body = json.loads(member.requests[1].content)
    assert body["scope"]["root_node_id"] == FULL_NODE


def test_a_full_scope_root_is_sent_without_a_lookup(member: PublicAPI) -> None:
    retrieve = f"/orgs/{FULL_ORG}/search/retrieve"
    member.serve(retrieve, fixture("search_scoped.json"))

    result = runner.invoke(
        app, ["nodes", "search", "payments", "--org", FULL_ORG, "--scope-root", ROOT_NODE]
    )

    assert result.exit_code == 0, result.output
    assert [path for path, _ in _requests(member)] == [retrieve]
    assert json.loads(member.requests[0].content)["scope"]["root_node_id"] == ROOT_NODE


def test_a_scope_root_with_no_branches_is_no_node(member: PublicAPI) -> None:
    """`branches.list` documents an empty list as "no such node"."""
    member.serve(f"/orgs/{FULL_ORG}/nodes/{SHORT_NODE}/branches", {"branches": [], "total": 0})

    result = runner.invoke(
        app, ["nodes", "search", "payments", "--org", FULL_ORG, "--scope-root", SHORT_NODE]
    )

    assert result.exit_code == 1
    assert f"No node '{SHORT_NODE}' in organization {FULL_ORG}" in plain(result.output)


# --- Short ids in tables, full ids in JSON ----------------------------------


def _orgs_listing() -> dict[str, object]:
    return {"organizations": [fixture("org_member.json")], "total": 1}


def test_orgs_list_shows_short_ids_and_json_keeps_them_whole(member: PublicAPI) -> None:
    member.serve("/orgs", _orgs_listing())

    table = runner.invoke(app, ["orgs", "list"])
    as_json = runner.invoke(app, ["orgs", "list", "--format", "json"])

    assert table.exit_code == 0, table.output
    assert f"{SHORT_ORG} Short ID demo org" in plain(table.output)
    assert FULL_ORG not in table.output
    assert json.loads(as_json.stdout)[0]["id"] == FULL_ORG


def test_search_shows_short_ids_and_json_keeps_them_whole(member: PublicAPI) -> None:
    member.serve(f"/orgs/{FULL_ORG}/search/retrieve", fixture("search.json"))
    argv = ["nodes", "search", "payments", "--org", FULL_ORG]

    table = runner.invoke(app, argv)
    as_json = runner.invoke(app, [*argv, "--format", "json"])

    assert table.exit_code == 0, table.output
    assert f"Payments API fts {SHORT_NODE}" in plain(table.output)
    assert FULL_NODE not in table.output
    assert json.loads(as_json.stdout)["matches"][0]["node_id"] == FULL_NODE


def test_nodes_list_across_orgs_shortens_both_ids(member: PublicAPI) -> None:
    """An org's listing, served as the cross-org one: the two share a shape."""
    member.serve("/orgs/all/nodes", fixture("nodes.json"))

    table = runner.invoke(app, ["nodes", "list"])
    as_json = runner.invoke(app, ["nodes", "list", "--format", "json"])

    assert table.exit_code == 0, table.output
    out = plain(table.output)
    # Matched in two halves: whether the title wraps depends on the width.
    assert f"{SHORT_NODE} Payments" in out
    assert f"0 {SHORT_ORG}" in out
    assert FULL_NODE not in table.output
    assert FULL_ORG not in table.output
    assert json.loads(as_json.stdout)[0]["id"] == FULL_NODE


# --- What counts as an id ---------------------------------------------------


@pytest.mark.parametrize("node_id", [SHORT_NODE[:7], "ab-7bd00e", "ab7bd00g", "payments"])
def test_anything_but_an_id_or_8_plus_characters_of_one_is_refused(
    public_api: PublicAPI, node_id: str
) -> None:
    result = runner.invoke(app, ["nodes", "show", node_id])

    assert result.exit_code == 1
    out = plain(result.output)
    assert "is not a node id" in out
    assert "at least its first 8 characters" in out
    assert public_api.requests == []


@pytest.mark.parametrize("org", [SHORT_ORG[:7], "dc-047318"])
def test_an_org_shorter_than_8_characters_is_refused(public_api: PublicAPI, org: str) -> None:
    result = runner.invoke(app, ["nodes", "list", "--org", org])

    assert result.exit_code == 1
    assert "is not an organization id" in plain(result.output)
    assert public_api.requests == []


def test_a_short_id_may_run_past_the_first_hyphen(member: PublicAPI) -> None:
    longer = FULL_NODE[:11]  # "ab7bd00e-00"
    member.serve(f"/nodes/{longer}", fixture("node_location.json"))
    member.serve(TREE, fixture("tree_document.json"))

    result = runner.invoke(app, ["nodes", "show", longer])

    assert result.exit_code == 0, result.output
    assert _requests(member) == [(f"/nodes/{longer}", True), (TREE, True)]
