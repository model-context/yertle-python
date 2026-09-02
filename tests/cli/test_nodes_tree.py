"""Tests for `yertle nodes tree`.

The interesting part is reassembly: the endpoint returns a flat list keyed by
each entry's *parent* path, so nesting, org grouping and the malformed-input
guards are what these pin down.

Fixtures mirror a real `GET /orgs/{id}/hierarchy` response, captured live:

    {"title": "Root",  "path": "/",     "depth": 0, "is_directory": true}
    {"title": "Thub",  "path": "/Root", "depth": 1, "is_directory": false}
    {"title": "API",   "path": "/Root/Yertle Webapp", "depth": 2, ...}

Paths are absolute and slash-prefixed. The first version of this file invented
paths without the leading slash; the tests passed and the command rendered only
its root nodes against the real API. Keep these shaped like the wire.
"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from yertle_client.models import HierarchyEntryResponse, HierarchyResponse

from yertle.cli._context import ORG_ENV_VAR
from yertle.cli.main import app

runner = CliRunner()

ORG = "8f14e45f-ceea-467a-9575-28db8d0dc4db"
OTHER_ORG = "1c383cd3-0b3f-4e1f-8e2a-9a1f0a0d1c2b"
_ORG_SCOPED = "yertle.nodes.get_org_hierarchy_orgs_org_id_hierarchy_get.sync"
_CROSS_ORG = "yertle.nodes.get_all_orgs_hierarchy_orgs_all_hierarchy_get.sync"


@pytest.fixture(autouse=True)
def _no_ambient_org(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.delenv(ORG_ENV_VAR, raising=False)


def _entry(
    node_id: str,
    title: str,
    path: str,
    depth: int,
    *,
    is_directory: bool = False,
    org_id: str = ORG,
    org_name: str = "Acme",
) -> HierarchyEntryResponse:
    return HierarchyEntryResponse(
        node_id=node_id,
        title=title,
        path=path,
        depth=depth,
        is_directory=is_directory,
        org_id=org_id,
        org_name=org_name,
    )


def _hierarchy() -> HierarchyResponse:
    """Platform contains Checkout and Payments; Checkout contains Cart."""
    entries = [
        _entry("n1", "Platform", "/", 0, is_directory=True),
        _entry("n2", "Checkout", "/Platform", 1, is_directory=True),
        _entry("n3", "Payments", "/Platform", 1),
        _entry("n4", "Cart", "/Platform/Checkout", 2),
    ]
    return HierarchyResponse(entries=entries, total=len(entries))


def _column_of(output: str, title: str) -> int:
    """Horizontal position of a title in the rendered tree — i.e. its depth."""
    line = next(line for line in output.splitlines() if title in line)
    return line.index(title)


@patch(_ORG_SCOPED, return_value=_hierarchy())
@patch("yertle._client.get_client", return_value=object())
def test_tree_nests_children_under_their_parent(_get_client, _sync) -> None:
    result = runner.invoke(app, ["nodes", "tree", "--org", ORG])
    assert result.exit_code == 0, result.output
    for title in ("Platform", "Checkout", "Payments", "Cart"):
        assert title in result.output, f"{title} missing — children did not attach"
    # Each level must be indented past the one above it.
    assert _column_of(result.output, "Checkout") > _column_of(result.output, "Platform")
    assert _column_of(result.output, "Cart") > _column_of(result.output, "Checkout")


@patch(_ORG_SCOPED, return_value=_hierarchy())
@patch("yertle._client.get_client", return_value=object())
def test_tree_json_format_returns_the_flat_entries(_get_client, _sync) -> None:
    result = runner.invoke(app, ["nodes", "tree", "--org", ORG, "--format", "json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert [e["title"] for e in parsed] == ["Platform", "Checkout", "Payments", "Cart"]


@patch(_CROSS_ORG, return_value=_hierarchy())
@patch("yertle._client.get_client", return_value=object())
def test_tree_defaults_to_every_org(_get_client, _sync) -> None:
    result = runner.invoke(app, ["nodes", "tree"])
    assert result.exit_code == 0, result.output
    assert "all organizations" in result.output


@patch("yertle._client.get_client", return_value=object())
def test_tree_keeps_identically_named_orgs_apart(_get_client) -> None:
    """Paths are unique only within an org.

    Two orgs that each contain a node called "Root" both produce children at
    "/Root". Without grouping by org first, each org's children attach to both
    trees. This is not hypothetical — a real account hit it.
    """
    entries = [
        _entry("a1", "Root", "/", 0, is_directory=True, org_id=ORG, org_name="Acme"),
        _entry("a2", "Acme Child", "/Root", 1, org_id=ORG, org_name="Acme"),
        _entry("b1", "Root", "/", 0, is_directory=True, org_id=OTHER_ORG, org_name="Beta"),
        _entry("b2", "Beta Child", "/Root", 1, org_id=OTHER_ORG, org_name="Beta"),
    ]
    response = HierarchyResponse(entries=entries, total=len(entries))
    with patch(_CROSS_ORG, return_value=response):
        result = runner.invoke(app, ["nodes", "tree"])

    assert result.exit_code == 0, result.output
    assert "Acme" in result.output
    assert "Beta" in result.output
    # Each child appears exactly once — not once under each org's Root.
    assert result.output.count("Acme Child") == 1
    assert result.output.count("Beta Child") == 1


@patch(_ORG_SCOPED, return_value=HierarchyResponse(entries=[], total=0))
@patch("yertle._client.get_client", return_value=object())
def test_tree_handles_an_empty_hierarchy(_get_client, _sync) -> None:
    result = runner.invoke(app, ["nodes", "tree", "--org", ORG])
    assert result.exit_code == 0
    assert "No nodes found" in result.output


@patch("yertle._client.get_client", return_value=object())
def test_tree_survives_a_self_referential_path(_get_client) -> None:
    """A hierarchy pointing at itself must not recurse forever."""
    entries = [
        _entry("n1", "Loop", "/", 0, is_directory=True),
        _entry("n2", "Loop", "/Loop", 1, is_directory=True),
    ]
    response = HierarchyResponse(entries=entries, total=2)
    with patch(_ORG_SCOPED, return_value=response):
        result = runner.invoke(app, ["nodes", "tree", "--org", ORG])
    assert result.exit_code == 0, result.output


@patch("yertle._client.get_client", return_value=object())
def test_tree_nests_under_a_title_containing_a_slash(_get_client) -> None:
    """The backend sanitises "/" to "-" when building paths; we must match.

    A node titled "a/b" has children at "/a-b", so sanitising the title the
    same way is what keeps them attached.
    """
    entries = [
        _entry("n1", "a/b", "/", 0, is_directory=True),
        _entry("n2", "child", "/a-b", 1),
    ]
    response = HierarchyResponse(entries=entries, total=2)
    with patch(_ORG_SCOPED, return_value=response):
        result = runner.invoke(app, ["nodes", "tree", "--org", ORG])
    assert result.exit_code == 0, result.output
    assert "a/b" in result.output
    assert "child" in result.output
    assert _column_of(result.output, "child") > _column_of(result.output, "a/b")
