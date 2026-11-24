"""Short ids: `yertle nodes show ab7bd00e`, `yertle nodes tree --org dc047318` (#60).

Served over an `httpx.MockTransport` from responses captured against a real
backend (see `tests/_short_ids.py`), so the real bindings build each URL and
parse each body. The mock does not resolve prefixes itself: each test serves
the path the CLI should request, with what the backend answered there.
"""

import pytest
from typer.testing import CliRunner

from tests._output import plain
from tests._public_api import PublicAPI, install_member
from tests._public_api import fixture as public_fixture
from tests._short_ids import (
    FULL_NODE,
    FULL_ORG,
    SHORT_NODE,
    SHORT_ORG,
    TWIN_NODE,
    UNMATCHED_NODE,
    UNMATCHED_ORG,
    fixture,
)
from yertle.cli._context import PUBLIC_FALLBACK_HINT
from yertle.cli.main import app

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


def test_anonymous_a_short_node_id_is_looked_up_in_public_orgs(public_api: PublicAPI) -> None:
    """No --org needed: the public lookup matches short ids in public orgs (yertle#608)."""
    lookup = f"/public/nodes/{SHORT_NODE}"
    public_api.serve(lookup, fixture("public_locate_short.json"))
    public_api.serve(PUBLIC_TREE, fixture("tree_document.json"))

    result = runner.invoke(app, ["nodes", "show", SHORT_NODE])

    assert result.exit_code == 0, result.output
    assert "Payments API" in result.output
    assert _requests(public_api) == [(lookup, False), (PUBLIC_TREE, False)]


def test_anonymous_a_named_org_is_checked_not_searched(public_api: PublicAPI) -> None:
    """--org is only a check now, as when signed in: a short org that matches passes."""
    lookup = f"/public/nodes/{SHORT_NODE}"
    public_api.serve(lookup, fixture("public_locate_short.json"))
    public_api.serve(PUBLIC_TREE, fixture("tree_document.json"))

    result = runner.invoke(app, ["nodes", "show", SHORT_NODE, "--org", SHORT_ORG])

    assert result.exit_code == 0, result.output
    assert _requests(public_api) == [(lookup, False), (PUBLIC_TREE, False)]


def test_anonymous_an_ambiguous_node_lists_the_matches(public_api: PublicAPI) -> None:
    lookup = f"/public/nodes/{SHORT_NODE}"
    public_api.serve(lookup, fixture("ambiguous_public_node_location.json"), status=409)

    result = runner.invoke(app, ["nodes", "show", SHORT_NODE])

    assert result.exit_code == 1
    out = plain(result.output)
    assert f"Short ID '{SHORT_NODE}' is ambiguous" in out
    assert FULL_NODE in out and TWIN_NODE in out


def test_anonymous_an_unmatched_node_is_the_public_not_found(public_api: PublicAPI) -> None:
    lookup = f"/public/nodes/{UNMATCHED_NODE}"
    public_api.serve(lookup, public_fixture("not_found_node_location.json"), status=404)

    result = runner.invoke(app, ["nodes", "show", UNMATCHED_NODE])

    assert result.exit_code == 1
    assert "or not a public organization" in plain(result.output)


# --- Signed in, not a member ------------------------------------------------


def test_a_non_member_reads_a_public_node_by_short_id(member: PublicAPI) -> None:
    """The lookup finds it in a public org; the read falls back to public (#70)."""
    member.serve(LOOKUP, fixture("nonmember_locate_short.json"))
    member.serve(TREE, public_fixture("forbidden_org_route.json"), status=403)
    member.serve(PUBLIC_TREE, fixture("tree_document.json"))

    result = runner.invoke(app, ["nodes", "show", SHORT_NODE])

    assert result.exit_code == 0, result.output
    assert "Payments API" in result.stdout
    assert PUBLIC_FALLBACK_HINT in plain(result.stderr)
    assert _requests(member) == [(LOOKUP, True), (TREE, True), (PUBLIC_TREE, False)]


def test_a_short_id_found_nowhere_is_just_not_found(member: PublicAPI) -> None:
    """No hint about orgs: the backend searched yours and every public one."""
    lookup = f"/nodes/{UNMATCHED_NODE}"
    member.serve(lookup, fixture("unmatched_node_location.json"), status=404)

    result = runner.invoke(app, ["nodes", "show", UNMATCHED_NODE])

    assert result.exit_code == 1
    out = plain(result.output)
    assert "404 from the API. Node not found" in out
    assert "--org" not in out
    assert _requests(member) == [(lookup, True)]


def test_a_non_member_sees_an_ambiguous_public_prefix_listed(member: PublicAPI) -> None:
    # The signed-in lookup answered a non-member with the same body as the
    # public route (both captured; identical).
    member.serve(LOOKUP, fixture("ambiguous_public_node_location.json"), status=409)

    result = runner.invoke(app, ["nodes", "show", SHORT_NODE])

    assert result.exit_code == 1
    out = plain(result.output)
    assert f"Short ID '{SHORT_NODE}' is ambiguous" in out
    assert FULL_NODE in out and TWIN_NODE in out
