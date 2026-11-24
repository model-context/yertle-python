"""Signed in, but not a member: reads of a public org fall back to its public routes (#70).

With a token the CLI uses the member routes, which refuse a non-member with
403, even for an org whose public routes would answer anyone. So on a 403,
and only then, each read tries its public counterpart.

Served over an `httpx.MockTransport` from responses captured against a real
backend (see `tests/_public_api.py`), including the 403 bodies the member
routes really return to a non-member. The member and public routes share one
recorded transport, so each test can check which requests were made and which
carried a token.
"""

import json

import pytest
from typer.testing import CliRunner

from tests._output import plain
from tests._public_api import ORG, PAYMENTS, PublicAPI, fixture, install_member
from yertle.cli._context import PUBLIC_FALLBACK_HINT
from yertle.cli.main import app

runner = CliRunner()

FORBIDDEN_ORG = fixture("forbidden_org.json")
FORBIDDEN_ROUTE = fixture("forbidden_org_route.json")

# Each read: argv, its member route with the 403 a non-member gets there, and
# its public route with the captured public response.
READS = {
    "orgs show": (
        ["orgs", "show", ORG],
        (f"/orgs/{ORG}", FORBIDDEN_ORG),
        (f"/public/orgs/{ORG}", fixture("org.json")),
    ),
    "nodes list": (
        ["nodes", "list", "--org", ORG],
        (f"/orgs/{ORG}/nodes", FORBIDDEN_ROUTE),
        (f"/public/orgs/{ORG}/nodes", fixture("nodes.json")),
    ),
    "nodes tree": (
        ["nodes", "tree", "--org", ORG],
        (f"/orgs/{ORG}/hierarchy", FORBIDDEN_ROUTE),
        (f"/public/orgs/{ORG}/hierarchy", fixture("hierarchy.json")),
    ),
    "nodes show": (
        ["nodes", "show", PAYMENTS],
        (f"/orgs/{ORG}/nodes/{PAYMENTS}/tree/main", FORBIDDEN_ROUTE),
        (f"/public/orgs/{ORG}/nodes/{PAYMENTS}/tree/main", fixture("tree_document.json")),
    ),
}

# What each read shows once it has its data: proof it rendered the public view.
SHOWS = {
    "orgs show": "Visibility",
    "nodes list": f"Nodes in public org {ORG} (6)",
    "nodes tree": f"Hierarchy in public org {ORG}",
    "nodes show": "Payments",
}


@pytest.fixture
def api(public_api: PublicAPI, token: str) -> PublicAPI:
    """A signed-in caller. `nodes show` looks its node up first, and finds it."""
    install_member(public_api, token)
    public_api.serve(f"/nodes/{PAYMENTS}", fixture("node_location_member.json"))
    return public_api


def _reads(api: PublicAPI) -> list[tuple[str, bool]]:
    """The requests after any node lookup: path, and whether a token went with it."""
    return [
        (r.url.path, "authorization" in r.headers)
        for r in api.requests
        if r.url.path != f"/nodes/{PAYMENTS}"
    ]


@pytest.mark.parametrize("name", READS)
def test_a_non_member_reads_a_public_org_through_its_public_routes(
    api: PublicAPI, name: str
) -> None:
    argv, (member_path, refused), (public_path, body) = READS[name]
    api.serve(member_path, refused, status=403)
    api.serve(public_path, body)

    result = runner.invoke(app, argv)

    assert result.exit_code == 0, result.output
    assert SHOWS[name] in plain(result.stdout)
    assert PUBLIC_FALLBACK_HINT in plain(result.stderr)
    # The member route first, with the token; then the public one, without.
    assert _reads(api) == [(member_path, True), (public_path, False)]


@pytest.mark.parametrize("name", READS)
def test_a_non_member_of_a_private_org_sees_the_403_as_before(api: PublicAPI, name: str) -> None:
    """The public route 404s: the org isn't public. The original refusal stands."""
    argv, (member_path, refused), (public_path, _) = READS[name]
    api.serve(member_path, refused, status=403)
    api.serve(public_path, fixture("not_found_private_org.json"), status=404)

    result = runner.invoke(app, argv)

    assert result.exit_code == 1
    out = plain(result.output)
    assert "403 Forbidden" in out
    assert refused["detail"] in out  # type: ignore[index]
    assert "public" not in out.lower()
    assert _reads(api) == [(member_path, True), (public_path, False)]


@pytest.mark.parametrize("name", READS)
@pytest.mark.parametrize("status", [401, 404, 500])
def test_only_a_403_falls_back(api: PublicAPI, name: str, status: int) -> None:
    """A bad token, a missing node or a server error is not "not a member"."""
    argv, (member_path, _), (public_path, body) = READS[name]
    api.serve(member_path, {"detail": "nope"}, status=status)
    api.serve(public_path, body)

    result = runner.invoke(app, argv)

    assert result.exit_code == 1
    assert [path for path, _ in _reads(api)] == [member_path]


def test_a_member_keeps_their_own_view_in_one_request(api: PublicAPI) -> None:
    api.serve(f"/orgs/{ORG}/hierarchy", fixture("hierarchy_member.json"))
    api.serve(f"/public/orgs/{ORG}/hierarchy", fixture("hierarchy.json"))

    result = runner.invoke(app, ["nodes", "tree", "--org", ORG])

    assert result.exit_code == 0, result.output
    assert f"Hierarchy in org {ORG}" in plain(result.stdout)
    assert PUBLIC_FALLBACK_HINT not in plain(result.output)
    assert _reads(api) == [(f"/orgs/{ORG}/hierarchy", True)]


@pytest.mark.parametrize("name", READS)
def test_json_after_a_fallback_is_only_the_public_response(api: PublicAPI, name: str) -> None:
    """The hint goes to stderr, so stdout parses as the public route's JSON."""
    argv, (member_path, refused), (public_path, body) = READS[name]
    api.serve(member_path, refused, status=403)
    api.serve(public_path, body)

    result = runner.invoke(app, [*argv, "--format", "json"])

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    if name == "nodes list":
        assert parsed == body["nodes"]  # type: ignore[index]
    elif name == "nodes tree":
        assert parsed == body["entries"]  # type: ignore[index]
    else:
        assert parsed == body
    assert PUBLIC_FALLBACK_HINT in plain(result.stderr)


def test_a_public_route_failure_other_than_404_is_reported(api: PublicAPI) -> None:
    """403, then a 500 from the public route: that is a real failure, not "private"."""
    api.serve(f"/orgs/{ORG}/nodes", FORBIDDEN_ROUTE, status=403)
    api.serve(f"/public/orgs/{ORG}/nodes", {"detail": "Internal Server Error"}, status=500)

    result = runner.invoke(app, ["nodes", "list", "--org", ORG])

    assert result.exit_code == 1
    out = plain(result.output)
    assert "500" in out
    assert "403" not in out
