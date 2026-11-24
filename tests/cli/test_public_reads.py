"""The CLI with no token: public orgs read anonymously, everything else refuses.

Served from responses captured against a real backend (see
`tests/_public_api.py`). No token resolves in any test here — the suite's
`isolate_config` fixture clears `$YERTLE_TOKEN` and points the config file at
an empty temp path.
"""

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner
from yertle_client.client import AuthenticatedClient

from tests._output import plain
from tests._public_api import (
    AUTH,
    BASE_URL,
    CHECKOUT,
    LEDGER,
    ORG,
    PAYMENTS,
    PRIVATE_NODE,
    PRIVATE_ORG,
    ROOT,
    SCRATCHPAD,
    PublicAPI,
    fixture,
)
from yertle import _client as _client_module
from yertle.cli.main import app
from yertle.shared import auth

runner = CliRunner()

NOT_AUTHENTICATED = "Not authenticated. Run `yertle login` or set $YERTLE_TOKEN."


@pytest.fixture
def served(public_api: PublicAPI) -> PublicAPI:
    public_api.serve(f"/public/orgs/{ORG}", fixture("org.json"))
    public_api.serve(f"/public/orgs/{ORG}/hierarchy", fixture("hierarchy.json"))
    public_api.serve(f"/public/orgs/{ORG}/nodes", fixture("nodes.json"))
    public_api.serve(
        f"/public/orgs/{ORG}/nodes/{PAYMENTS}/tree/main",
        fixture("tree_document.json"),
    )
    public_api.serve(f"/public/nodes/{PAYMENTS}", fixture("node_location.json"))
    return public_api


def _no_token_sent(api: PublicAPI) -> None:
    assert api.requests, "expected at least one request"
    for request in api.requests:
        assert request.url.path.startswith("/public/")
        assert "authorization" not in request.headers


def test_orgs_show_reads_a_public_org(served: PublicAPI) -> None:
    result = runner.invoke(app, ["orgs", "show", ORG])

    assert result.exit_code == 0, result.output
    out = plain(result.output)
    assert "Example public org" in out
    assert "A public org used by the tests." in out
    assert "Members 1" in out
    assert "Nodes 6" in out
    assert "Visibility public" in out
    assert "yertle login" in out
    _no_token_sent(served)


def test_orgs_show_json_is_the_public_org_response(served: PublicAPI) -> None:
    result = runner.invoke(app, ["orgs", "show", ORG, "--format", "json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == fixture("org.json")


def test_nodes_list_reads_a_public_org(served: PublicAPI) -> None:
    result = runner.invoke(app, ["nodes", "list", "--org", ORG])

    assert result.exit_code == 0, result.output
    assert f"Nodes in public org {ORG} (6)" in plain(result.output)
    _no_token_sent(served)


def test_nodes_list_json_carries_every_node(served: PublicAPI) -> None:
    result = runner.invoke(app, ["nodes", "list", "--org", ORG, "--format", "json"])

    assert result.exit_code == 0, result.output
    titles = sorted(node["title"] for node in json.loads(result.output))
    assert titles == [
        "Auth / Sessions",
        "Checkout API",
        "Ledger DB",
        "Payments",
        "Root",
        "Scratchpad",
    ]


def test_nodes_tree_reads_a_public_org(served: PublicAPI) -> None:
    result = runner.invoke(app, ["nodes", "tree", "--org", ORG])

    assert result.exit_code == 0, result.output
    lines = [line.strip("│├└─ ") for line in result.output.splitlines()]
    # Seven entries for six nodes: Ledger DB has a row per parent.
    assert lines[0] == f"Hierarchy in public org {ORG} (7)"
    # Ledger DB has two parents and appears under both; Scratchpad is
    # attached to nothing, so it is a root beside Root.
    # Ids are short in the tree, as in every table (#60). These fixtures'
    # ids all begin 00000000, so the titles carry the structure here.
    assert lines[1:] == [
        f"Root  {ROOT[:8]}",
        f"Auth / Sessions  {AUTH[:8]}",
        f"Checkout API  {CHECKOUT[:8]}",
        f"Ledger DB  {LEDGER[:8]}",
        f"Payments  {PAYMENTS[:8]}",
        f"Ledger DB  {LEDGER[:8]}",
        f"Scratchpad  {SCRATCHPAD[:8]}",
    ]
    _no_token_sent(served)


def test_nodes_tree_json_is_what_a_member_gets(
    served: PublicAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Captured from one org, anonymously and by its owner: the output must not differ."""
    anonymous = runner.invoke(app, ["nodes", "tree", "--org", ORG, "--format", "json"])
    assert anonymous.exit_code == 0, anonymous.output
    _no_token_sent(served)

    served.serve(f"/orgs/{ORG}/hierarchy", fixture("hierarchy_member.json"))
    _client_module._default_client = AuthenticatedClient(  # pyright: ignore[reportPrivateUsage]
        base_url=BASE_URL,
        token="yrt_member",
        raise_on_unexpected_status=True,
        httpx_args={"transport": httpx.MockTransport(served.handle)},
    )
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "yrt_member")
    member = runner.invoke(app, ["nodes", "tree", "--org", ORG, "--format", "json"])
    assert member.exit_code == 0, member.output
    assert served.requests[-1].url.path == f"/orgs/{ORG}/hierarchy"

    assert member.output == anonymous.output


def test_nodes_show_reads_a_public_node(served: PublicAPI) -> None:
    """No org given: the public lookup finds it, then the public read uses it."""
    result = runner.invoke(app, ["nodes", "show", PAYMENTS])

    assert result.exit_code == 0, result.output
    out = plain(result.output)
    assert "Payments" in out
    assert "Ledger DB" in out
    assert "Checkout API → this charges" in out
    assert [request.url.path for request in served.requests] == [
        f"/public/nodes/{PAYMENTS}",
        f"/public/orgs/{ORG}/nodes/{PAYMENTS}/tree/main",
    ]
    _no_token_sent(served)


def test_nodes_show_checks_a_named_org_against_the_node(served: PublicAPI) -> None:
    result = runner.invoke(app, ["nodes", "show", PAYMENTS, "--org", ORG])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["nodes", "show", PAYMENTS, "--org", PRIVATE_ORG])
    assert result.exit_code == 1
    out = plain(result.output)
    assert f"is in organization {ORG} (Example public org)" in out
    assert f"not {PRIVATE_ORG}, which came from --org" in out
    assert served.requests[-1].url.path == f"/public/nodes/{PAYMENTS}"
    _no_token_sent(served)


def test_nodes_show_of_a_private_node_is_the_public_not_found(public_api: PublicAPI) -> None:
    """The public lookup 404s for a private node exactly as for a missing one."""
    public_api.serve(
        f"/public/nodes/{PRIVATE_NODE}", fixture("not_found_node_location.json"), status=404
    )

    result = runner.invoke(app, ["nodes", "show", PRIVATE_NODE])

    assert result.exit_code == 1
    assert "Not found at https://api.yertle.com, or not a public organization." in plain(
        result.output
    )
    assert [request.url.path for request in public_api.requests] == [
        f"/public/nodes/{PRIVATE_NODE}"
    ]
    _no_token_sent(public_api)


@pytest.mark.parametrize(
    "argv",
    [
        ["orgs", "show", ORG],
        ["nodes", "list", "--org", ORG],
        ["nodes", "tree", "--org", ORG],
        ["nodes", "show", PAYMENTS, "--org", ORG],
        ["nodes", "show", PAYMENTS],
    ],
)
def test_a_private_or_missing_org_explains_itself(public_api: PublicAPI, argv: list[str]) -> None:
    """The backend 404s for both, so the message has to name both."""
    result = runner.invoke(app, argv)

    assert result.exit_code == 1
    out = plain(result.output)
    assert "Not found at https://api.yertle.com, or not a public organization." in out
    assert "yertle login" in out
    _no_token_sent(public_api)


@pytest.mark.parametrize("command", ["list", "tree"])
def test_nodes_without_an_org_says_to_pass_one(public_api: PublicAPI, command: str) -> None:
    """The default is every org you belong to, which means nothing anonymously."""
    result = runner.invoke(app, ["nodes", command])

    assert result.exit_code == 1
    assert NOT_AUTHENTICATED in result.output
    assert "pass --org <id>" in result.output
    assert public_api.requests == []


@pytest.mark.parametrize(
    "argv",
    [
        ["orgs", "list"],
        ["orgs", "create", "New org"],
        ["nodes", "search", "payments", "--org", ORG],
        ["nodes", "create", "New node", "--org", ORG],
        ["nodes", "delete", PAYMENTS, "--org", ORG, "--yes"],
        ["branches", "list", PAYMENTS, "--org", ORG],
        # Node commands with no org would look it up first; only a read may
        # do that anonymously, so these fail before any request.
        ["nodes", "delete", PAYMENTS, "--yes"],
        ["branches", "list", PAYMENTS],
        ["branches", "create", PAYMENTS, "feature"],
        ["branches", "delete", PAYMENTS, "feature"],
        ["prs", "list", PAYMENTS],
        ["prs", "show", PAYMENTS, "1"],
        ["prs", "create", PAYMENTS, "Title", "--source", "feature"],
        ["prs", "merge", PAYMENTS, "1"],
        ["prs", "close", PAYMENTS, "1"],
    ],
)
def test_everything_else_still_needs_a_token(public_api: PublicAPI, argv: list[str]) -> None:
    result = runner.invoke(app, argv)

    assert result.exit_code == 1, result.output
    assert NOT_AUTHENTICATED in plain(result.output)
    assert public_api.requests == []


def test_with_a_token_reads_stay_on_the_member_routes(token: str, public_api: PublicAPI) -> None:
    with patch("yertle.cli.commands.orgs._merged", side_effect=SystemExit(0)) as merged:
        runner.invoke(app, ["orgs", "show", ORG])

    merged.assert_called_once_with(ORG)
    assert public_api.requests == []


def test_a_corrupt_config_is_a_sentence_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Deciding whether to read anonymously reads the config, so it can fail too."""
    config = tmp_path / "config.json"
    config.write_text("{not json")
    monkeypatch.setattr(auth, "CONFIG_PATH", config)

    result = runner.invoke(app, ["nodes", "tree", "--org", ORG])

    assert result.exit_code == 1
    assert "is not valid JSON" in result.output
    assert "Traceback" not in result.output


def test_an_empty_public_org_says_so(public_api: PublicAPI) -> None:
    public_api.serve(f"/public/orgs/{ORG}/hierarchy", {"entries": [], "total": 0})

    result = runner.invoke(app, ["nodes", "tree", "--org", ORG])

    assert result.exit_code == 0, result.output
    assert "No nodes found." in result.output
    _no_token_sent(public_api)
