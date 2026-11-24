"""Commands that take a node id find its organization from the node.

Served over an `httpx.MockTransport` from lookups captured against a real
backend (see `tests/_public_api.py`), so the real bindings build each URL and
parse each body. With a token here; `test_public_reads.py` covers the
anonymous lookup.
"""

import json

import pytest
from typer.testing import CliRunner
from yertle_client.errors import UnexpectedStatus

from tests._output import plain
from tests._public_api import (
    ORG,
    PAYMENTS,
    PRIVATE_NODE,
    PRIVATE_ORG,
    PublicAPI,
    fixture,
    install_member,
)
from yertle.cli._context import ORG_ENV_VAR
from yertle.cli._errors import api_error_message
from yertle.cli.main import app

runner = CliRunner()

LOOKUP = f"/nodes/{PAYMENTS}"
TREE = f"/orgs/{ORG}/nodes/{PAYMENTS}/tree/main"


@pytest.fixture
def api(public_api: PublicAPI, token: str) -> PublicAPI:
    """A member's view: the lookup and the read both go through the token routes."""
    install_member(public_api, token)
    public_api.serve(LOOKUP, fixture("node_location_member.json"))
    public_api.serve(TREE, fixture("tree_document.json"))
    return public_api


def _paths(api: PublicAPI) -> list[str]:
    return [request.url.path for request in api.requests]


def test_no_org_anywhere_is_looked_up(api: PublicAPI) -> None:
    result = runner.invoke(app, ["nodes", "show", PAYMENTS])

    assert result.exit_code == 0, result.output
    assert "Payments" in plain(result.output)
    assert _paths(api) == [LOOKUP, TREE]
    assert all(request.headers["authorization"] for request in api.requests)


@pytest.mark.parametrize("argv", [["--org", ORG], ["--org", "all"]])
def test_a_matching_or_unspecific_org_is_accepted(api: PublicAPI, argv: list[str]) -> None:
    result = runner.invoke(app, ["nodes", "show", PAYMENTS, *argv])

    assert result.exit_code == 0, result.output
    assert _paths(api) == [LOOKUP, TREE]


def test_a_mismatched_org_names_both_and_reads_nothing(api: PublicAPI) -> None:
    result = runner.invoke(app, ["nodes", "show", PAYMENTS, "--org", PRIVATE_ORG])

    assert result.exit_code == 1
    out = plain(result.output)
    assert f"Node {PAYMENTS} is in organization {ORG} (Example public org)" in out
    assert f"not {PRIVATE_ORG}, which came from --org" in out
    assert _paths(api) == [LOOKUP]


def test_a_mismatched_env_org_says_where_it_came_from(
    api: PublicAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ORG_ENV_VAR, PRIVATE_ORG)

    result = runner.invoke(app, ["nodes", "show", PAYMENTS])

    assert result.exit_code == 1
    assert f"which came from ${ORG_ENV_VAR}" in plain(result.output)


def test_a_write_with_a_mismatched_org_writes_nothing(api: PublicAPI) -> None:
    result = runner.invoke(app, ["nodes", "delete", PAYMENTS, "--org", PRIVATE_ORG, "--yes"])

    assert result.exit_code == 1
    assert "which came from --org" in plain(result.output)
    assert _paths(api) == [LOOKUP]


def test_a_malformed_org_fails_before_any_request(api: PublicAPI) -> None:
    result = runner.invoke(app, ["nodes", "show", PAYMENTS, "--org", "not-an-org"])

    assert result.exit_code == 1
    assert "'not-an-org' is not an organization id" in plain(result.output)
    assert api.requests == []


def test_a_node_you_cannot_see_reads_as_it_did_before(api: PublicAPI) -> None:
    """The lookup's 404 is the org-scoped read's 404, so the message is unchanged."""
    body = fixture("not_found_node_location_member.json")
    api.serve(f"/nodes/{PRIVATE_NODE}", body, status=404)

    result = runner.invoke(app, ["nodes", "show", PRIVATE_NODE])

    assert result.exit_code == 1
    before = api_error_message(UnexpectedStatus(404, json.dumps(body).encode()))
    assert plain(result.output) == plain(before)
    assert "Node not found" in before
    assert _paths(api) == [f"/nodes/{PRIVATE_NODE}"]


def test_a_node_in_a_private_org_is_found_with_a_token(public_api: PublicAPI, token: str) -> None:
    """The case anonymous lookup cannot answer: a member's own private org."""
    install_member(public_api, token)
    public_api.serve(f"/nodes/{PRIVATE_NODE}", fixture("node_location_private.json"))
    public_api.serve(
        f"/orgs/{PRIVATE_ORG}/nodes/{PRIVATE_NODE}/branches", {"branches": [], "total": 0}
    )

    result = runner.invoke(app, ["branches", "list", PRIVATE_NODE])

    assert result.exit_code == 0, result.output
    assert _paths(public_api) == [
        f"/nodes/{PRIVATE_NODE}",
        f"/orgs/{PRIVATE_ORG}/nodes/{PRIVATE_NODE}/branches",
    ]
