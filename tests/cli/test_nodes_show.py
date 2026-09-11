"""Tests for `yertle nodes show`.

`_COMPLETE` is a trimmed **capture** of a real
`GET /orgs/{id}/nodes/{id}/tree/main/complete` response, not a hand-written
approximation. Two shapes in it would have been guessed wrong from the
architecture doc alone:

- `tags` nests its values — `{"Team": {"value": "Backend"}}`, not
  `{"Team": "Backend"}`.
- internal connections key off `from_child_id` / `to_child_id`, while the doc
  shows `from_node_id` / `to_node_id` (which is the *ingress/egress* shape).

Inventing fixtures is what let the `nodes tree` path bug ship green, so keep
these captured.
"""

import json
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from yertle_client.models import NodeCompleteStateResponse

from yertle.cli.main import app

runner = CliRunner()

ORG = "f586beac-7039-4f0c-9681-fd36293f071f"
NODE = "09b27471-7aa2-4ff2-8f4e-ca62941f06df"
_GET = "yertle.nodes._complete.sync"

_COMPLETE: dict[str, Any] = {
    "node": {
        "id": NODE,
        "org_id": ORG,
        "title": "Yertle Webapp",
        "description": "The customer-facing app.",
        "created_at": "2026-04-15T00:58:22.292611+00:00",
    },
    "tags": {"Team": {"value": "Backend"}},
    "directories": ["/services"],
    "child_nodes": [
        {"id": "0b8cb5f2", "title": "Cognito", "description": "User pool."},
        {"id": "0cc209f2", "title": "API Gateway", "description": "HTTP API."},
    ],
    "connections": [
        {
            "id": "4d79f7b3",
            "from_child_id": "0cc209f2",
            "to_child_id": "0b8cb5f2",
            "label": None,
            "type": "default",
        },
    ],
    "parent_nodes": [{"id": "bbbff903", "title": "Root", "description": ""}],
    "ingress_connections": [
        {
            "connection_id": "638f13ef",
            "from_node_id": "e4222c72",
            "to_node_id": NODE,
            "label": "signs in",
            "connected_node": {"title": "User", "description": ""},
        },
    ],
    "egress_connections": [
        {
            "connection_id": "4d79f7b3",
            "from_node_id": NODE,
            "to_node_id": "79606437",
            "label": None,
            "connected_node": {"title": "Lambda", "description": ""},
        },
    ],
}


def _response(**overrides: object) -> NodeCompleteStateResponse:
    return NodeCompleteStateResponse.from_dict({**_COMPLETE, **overrides})


@pytest.fixture
def _default_org(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.setenv("YERTLE_ORG", ORG)


@patch(_GET, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_show_renders_every_section(_get_client, _sync, _default_org) -> None:
    result = runner.invoke(app, ["nodes", "show", NODE])
    assert result.exit_code == 0, result.output

    assert "Yertle Webapp" in result.output
    assert "branch main" in result.output
    assert "The customer-facing app." in result.output
    assert "Backend" in result.output  # tag value, unwrapped from {"value": ...}
    assert "/services" in result.output
    assert "Root" in result.output  # parent
    assert "Cognito" in result.output  # child
    assert "API Gateway → Cognito" in result.output  # ids resolved to titles
    assert "User → this" in result.output  # ingress
    assert "this → Lambda" in result.output  # egress
    assert "signs in" in result.output  # connection label


@patch(_GET, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_show_json_dumps_an_object_not_a_list(_get_client, _sync, _default_org) -> None:
    """`… --format json | jq .node.title` should work."""
    result = runner.invoke(app, ["nodes", "show", NODE, "--format", "json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert isinstance(parsed, dict)
    assert parsed["node"]["title"] == "Yertle Webapp"


@patch("yertle._client.get_client", return_value=object())
def test_show_omits_empty_sections(_get_client, _default_org) -> None:
    """A sparse node should read as a short page, not a form full of blanks."""
    bare = _response(
        tags={},
        directories=[],
        child_nodes=[],
        connections=[],
        parent_nodes=[],
        ingress_connections=[],
        egress_connections=[],
    )
    with patch(_GET, return_value=bare):
        result = runner.invoke(app, ["nodes", "show", NODE])

    assert result.exit_code == 0, result.output
    assert "Yertle Webapp" in result.output
    for heading in ("Tags", "Directories", "Parents", "Children", "Ingress", "Egress"):
        assert heading not in result.output


@patch(_GET, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_show_passes_the_branch_through(_get_client, sync, _default_org) -> None:
    result = runner.invoke(app, ["nodes", "show", NODE, "--branch", "feature-x"])
    assert result.exit_code == 0, result.output
    assert sync.call_args.kwargs["branch"] == "feature-x"
    assert "branch feature-x" in result.output


def test_show_requires_a_single_org(monkeypatch: pytest.MonkeyPatch) -> None:
    """'all' cannot address one node, so say which levers set an org."""
    monkeypatch.setenv("YERTLE_ORG", "all")
    result = runner.invoke(app, ["nodes", "show", NODE])
    assert result.exit_code == 1
    assert "needs one organization" in result.output
    assert "yertle orgs use" in result.output


@patch("yertle._client.get_client", return_value=object())
def test_show_survives_an_unknown_connection_endpoint(_get_client, _default_org) -> None:
    """A connection naming a child that is not listed must not raise."""
    orphaned = _response(
        connections=[
            {
                "id": "x",
                "from_child_id": "not-in-children",
                "to_child_id": "0b8cb5f2",
                "label": None,
            },
        ],
    )
    with patch(_GET, return_value=orphaned):
        result = runner.invoke(app, ["nodes", "show", NODE])

    assert result.exit_code == 0, result.output
    assert "? → Cognito" in result.output


@patch("yertle._client.get_client", return_value=object())
def test_show_handles_a_flat_tag_value(_get_client, _default_org) -> None:
    """Tags nest today, but a flat value must print rather than raise.

    The unwrap is defensive on purpose: this is a display command, and a tag
    shape the CLI does not expect should degrade to showing it, not to a
    traceback.
    """
    with patch(_GET, return_value=_response(tags={"Team": "Backend", "Tier": {}})):
        result = runner.invoke(app, ["nodes", "show", NODE])

    assert result.exit_code == 0, result.output
    assert "Backend" in result.output
    assert "Tier" in result.output
