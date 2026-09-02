"""Tests for the `yertle nodes` command group.

Mocks the wire layer, so these exercise the real
CLI → `yertle.nodes` → `yertle_client` path.
"""

import datetime
import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from yertle_client.models import NodeListResponse, NodeResponse

from yertle.cli._context import ORG_ENV_VAR
from yertle.cli.main import app

runner = CliRunner()

ORG = "8f14e45f-ceea-467a-9575-28db8d0dc4db"
_ORG_SCOPED = "yertle.nodes.list_nodes_orgs_org_id_nodes_get.sync"
_CROSS_ORG = "yertle.nodes.list_all_nodes_across_orgs_orgs_all_nodes_get.sync"


@pytest.fixture(autouse=True)
def _no_ambient_org(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.delenv(ORG_ENV_VAR, raising=False)


def _response() -> NodeListResponse:
    now = datetime.datetime(2026, 9, 2, tzinfo=datetime.UTC)
    return NodeListResponse(
        nodes=[
            NodeResponse(
                id="node-1",
                title="Checkout API",
                description="",
                org_id=ORG,
                public_id="checkout-api",
                created_by="someone",
                created_at=now,
                num_children=3,
                num_parents=1,
            ),
            NodeResponse(
                id="node-2",
                title="Payments DB",
                description="",
                org_id=ORG,
                public_id="payments-db",
                created_by="someone",
                created_at=now,
            ),
        ],
        total=2,
        limit=50,
        offset=0,
    )


@patch(_ORG_SCOPED, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_nodes_list_table_format(_get_client, _sync) -> None:
    result = runner.invoke(app, ["nodes", "list", "--org", ORG])
    assert result.exit_code == 0, result.output
    assert "Checkout API" in result.output
    assert "Payments DB" in result.output


@patch(_ORG_SCOPED, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_nodes_list_json_format(_get_client, _sync) -> None:
    result = runner.invoke(app, ["nodes", "list", "--org", ORG, "--format", "json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert [n["title"] for n in parsed] == ["Checkout API", "Payments DB"]


@patch(_CROSS_ORG, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_nodes_list_defaults_to_every_org(_get_client, _sync) -> None:
    result = runner.invoke(app, ["nodes", "list"])
    assert result.exit_code == 0, result.output
    assert "all organizations" in result.output


@patch(_ORG_SCOPED, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_nodes_list_reads_the_org_env_var(
    _get_client,
    _sync,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ORG_ENV_VAR, ORG)
    result = runner.invoke(app, ["nodes", "list"])
    assert result.exit_code == 0, result.output
    assert ORG in result.output


def test_nodes_list_rejects_a_malformed_org() -> None:
    result = runner.invoke(app, ["nodes", "list", "--org", "acme-corp"])
    assert result.exit_code == 1
    assert "not an organization id" in result.output


def test_nodes_is_a_group_not_a_command() -> None:
    result = runner.invoke(app, ["nodes"])
    assert "list" in result.output
    assert "Checkout API" not in result.output


@patch(_ORG_SCOPED, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_missing_counts_render_as_a_dash(_get_client, _sync) -> None:
    """An uncomputed count is not zero, and must not look like one."""
    result = runner.invoke(app, ["nodes", "list", "--org", ORG])
    assert "—" in result.output
