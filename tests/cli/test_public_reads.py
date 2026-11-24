"""The CLI with no token: public orgs read anonymously, everything else refuses.

Served from responses captured against a real backend (see
`tests/_public_api.py`). No token resolves in any test here — the suite's
`isolate_config` fixture clears `$YERTLE_TOKEN` and points the config file at
an empty temp path.
"""

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console
from rich.tree import Tree
from typer.testing import CliRunner
from yertle_client.models import HierarchyResponse, OrgGraphResponse

from tests._output import plain
from tests._public_api import CHECKOUT, LEDGER, ORG, PAYMENTS, ROOT, PublicAPI, fixture
from yertle.cli.commands.nodes import (  # pyright: ignore[reportPrivateUsage]
    _build_tree,
    _graph_tree,
)
from yertle.cli.main import app
from yertle.shared import auth

runner = CliRunner()

NOT_AUTHENTICATED = "Not authenticated. Run `yertle login` or set $YERTLE_TOKEN."


@pytest.fixture
def served(public_api: PublicAPI) -> PublicAPI:
    public_api.serve(f"/public/orgs/{ORG}/graph", fixture("graph.json"))
    public_api.serve(f"/public/orgs/{ORG}/nodes", fixture("nodes.json"))
    public_api.serve(
        f"/public/orgs/{ORG}/nodes/{PAYMENTS}/tree/main",
        fixture("tree_document.json"),
    )
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
    assert "Nodes 4" in out
    assert "Visibility public" in out
    assert "yertle login" in out
    _no_token_sent(served)


def test_orgs_show_json_uses_the_public_org_field_names(served: PublicAPI) -> None:
    result = runner.invoke(app, ["orgs", "show", ORG, "--format", "json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"id": ORG, "name": "Example public org", "node_count": 4}


def test_nodes_list_reads_a_public_org(served: PublicAPI) -> None:
    result = runner.invoke(app, ["nodes", "list", "--org", ORG])

    assert result.exit_code == 0, result.output
    assert f"Nodes in public org {ORG} (4)" in plain(result.output)
    _no_token_sent(served)


def test_nodes_list_json_carries_every_node(served: PublicAPI) -> None:
    result = runner.invoke(app, ["nodes", "list", "--org", ORG, "--format", "json"])

    assert result.exit_code == 0, result.output
    titles = sorted(node["title"] for node in json.loads(result.output))
    assert titles == ["Checkout API", "Ledger DB", "Payments", "Root"]


def test_nodes_tree_reads_a_public_org(served: PublicAPI) -> None:
    result = runner.invoke(app, ["nodes", "tree", "--org", ORG])

    assert result.exit_code == 0, result.output
    lines = [line.strip("│├└─ ") for line in result.output.splitlines()]
    assert lines[0] == f"Hierarchy in public org {ORG} (4)"
    assert lines[1:] == [
        f"Root  {ROOT}",
        f"Checkout API  {CHECKOUT}",
        f"Payments  {PAYMENTS}",
        f"Ledger DB  {LEDGER}",
    ]
    _no_token_sent(served)


def test_nodes_tree_json_is_the_graph(served: PublicAPI) -> None:
    result = runner.invoke(app, ["nodes", "tree", "--org", ORG, "--format", "json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["total_nodes"] == 4


def _drawn(tree: Tree) -> str:
    console = Console(width=200, record=True, file=io.StringIO())
    console.print(tree)
    return console.export_text()


def test_the_public_tree_matches_a_members_tree_of_the_same_org() -> None:
    """Both captures are of the same org: the graph read anonymously, the
    hierarchy read by its owner. Built from either, the tree must agree."""
    graph = OrgGraphResponse.from_dict(fixture("graph.json"))  # type: ignore[arg-type]
    hierarchy = HierarchyResponse.from_dict(fixture("hierarchy_same_org.json"))  # type: ignore[arg-type]

    assert _drawn(_graph_tree(graph, "label")) == _drawn(_build_tree(hierarchy.entries, "label"))


def test_graph_tree_survives_a_cycle_with_no_root() -> None:
    graph = OrgGraphResponse.from_dict(
        {
            "nodes": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
            "edges": [
                {"source": "a", "target": "b", "edge_type": "parent_child"},
                {"source": "b", "target": "a", "edge_type": "parent_child"},
                {"source": "a", "target": "b", "edge_type": "connection"},
            ],
            "total_nodes": 2,
            "total_edges": 3,
        },
    )
    text = _drawn(_graph_tree(graph, "label"))
    assert "A  a" in text
    assert "B  b" in text


def test_nodes_show_reads_a_public_node(served: PublicAPI) -> None:
    result = runner.invoke(app, ["nodes", "show", PAYMENTS, "--org", ORG])

    assert result.exit_code == 0, result.output
    out = plain(result.output)
    assert "Payments" in out
    assert "Ledger DB" in out
    assert "Checkout API → this charges" in out
    _no_token_sent(served)


@pytest.mark.parametrize(
    "argv",
    [
        ["orgs", "show", ORG],
        ["nodes", "list", "--org", ORG],
        ["nodes", "tree", "--org", ORG],
        ["nodes", "show", PAYMENTS, "--org", ORG],
    ],
)
def test_a_private_or_missing_org_explains_itself(public_api: PublicAPI, argv: list[str]) -> None:
    """The backend 404s for both, so the message has to name both."""
    result = runner.invoke(app, argv)

    assert result.exit_code == 1
    out = plain(result.output)
    assert "Not found at https://api.yertle.com, or not a public organization." in out
    assert "yertle login" in out


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
    empty = {"nodes": [], "edges": [], "total_nodes": 0, "total_edges": 0, "org_name": "Empty"}
    public_api.serve(f"/public/orgs/{ORG}/graph", empty)

    result = runner.invoke(app, ["nodes", "tree", "--org", ORG])

    assert result.exit_code == 0, result.output
    assert "No nodes found." in result.output
