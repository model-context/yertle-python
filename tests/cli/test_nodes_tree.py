"""Tests for `yertle nodes tree`.

The interesting part is reassembly: the endpoint returns a flat list keyed by
each entry's *parent* path, so nesting, ordering and the malformed-input guard
are what these pin down.
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
) -> HierarchyEntryResponse:
    return HierarchyEntryResponse(
        node_id=node_id,
        title=title,
        path=path,
        depth=depth,
        is_directory=is_directory,
        org_id=ORG,
    )


def _hierarchy() -> HierarchyResponse:
    """Platform contains Checkout and Payments; Checkout contains Cart."""
    entries = [
        _entry("n1", "Platform", "/", 0, is_directory=True),
        _entry("n2", "Checkout", "Platform", 1, is_directory=True),
        _entry("n3", "Payments", "Platform", 1),
        _entry("n4", "Cart", "Platform/Checkout", 2),
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
        assert title in result.output
    # Cart sits a level below Checkout, so it must be indented further.
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
        _entry("n2", "Loop", "Loop", 1, is_directory=True),
    ]
    response = HierarchyResponse(entries=entries, total=2)
    with patch(_ORG_SCOPED, return_value=response):
        result = runner.invoke(app, ["nodes", "tree", "--org", ORG])
    assert result.exit_code == 0, result.output


@patch("yertle._client.get_client", return_value=object())
def test_tree_does_not_let_a_slash_in_a_title_forge_a_path(_get_client) -> None:
    """A title containing "/" must not silently reparent anything."""
    entries = [
        _entry("n1", "a/b", "/", 0, is_directory=True),
        _entry("n2", "child", "a/b", 1),
    ]
    response = HierarchyResponse(entries=entries, total=2)
    with patch(_ORG_SCOPED, return_value=response):
        result = runner.invoke(app, ["nodes", "tree", "--org", ORG])
    assert result.exit_code == 0, result.output
    assert "a/b" in result.output
    # "child" is keyed to the raw path "a/b", which sanitisation turns into
    # "a-b" — so it is deliberately NOT nested under it.
    assert "child" not in result.output
