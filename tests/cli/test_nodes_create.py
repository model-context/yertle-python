"""Tests for `yertle nodes create` — the CLI's first write command.

Mocks the wire layer, so these exercise the real
CLI -> `yertle.nodes` -> `yertle_client` path. The assertions that matter are
about the *request body*: which optional fields are sent, and which are left
off so the backend's own defaults apply.
"""

import datetime
import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from yertle_client.models import CreateNodeRequest, NodeResponse
from yertle_client.types import UNSET, Unset

from yertle.cli._context import ORG_ENV_VAR
from yertle.cli.main import app

runner = CliRunner()

ORG = "8f14e45f-ceea-467a-9575-28db8d0dc4db"
_CREATE = "yertle.nodes.create_node_orgs_org_id_nodes_post.sync"


@pytest.fixture(autouse=True)
def _no_ambient_org(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.delenv(ORG_ENV_VAR, raising=False)


def _created(title: str = "Checkout API") -> NodeResponse:
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    return NodeResponse(
        id="11111111-2222-3333-4444-555555555555",
        title=title,
        description="",
        org_id=ORG,
        public_id="checkout-api-abc123",
        created_by="someone",
        created_at=now,
    )


def _body(sync_mock) -> CreateNodeRequest:
    """The request body the CLI actually sent.

    Typed rather than left as `object` so the assertions below are checked
    against the real model — a renamed wire field fails `make check` instead
    of silently asserting nothing.
    """
    body = sync_mock.call_args.kwargs["body"]
    assert isinstance(body, CreateNodeRequest)
    return body


@patch(_CREATE, return_value=_created())
@patch("yertle._client.get_client", return_value=object())
def test_create_sends_only_the_title_when_nothing_else_is_given(_client, sync) -> None:
    """Unset options must not be sent, or they override the backend's defaults.

    `description` defaults to "" server-side and `commit_message` to
    'Initial commit'. Sending null for either replaces a working default with
    nothing.
    """
    result = runner.invoke(app, ["nodes", "create", "Checkout API", "--org", ORG])
    assert result.exit_code == 0, result.output

    body = _body(sync)
    assert body.title == "Checkout API"
    assert body.description is UNSET
    assert body.tags is UNSET
    assert body.directories is UNSET
    assert body.public_id is UNSET
    assert body.commit_message is UNSET


@patch(_CREATE, return_value=_created())
@patch("yertle._client.get_client", return_value=object())
def test_create_sends_every_option_it_is_given(_client, sync) -> None:
    result = runner.invoke(
        app,
        [
            "nodes", "create", "Checkout API",
            "--org", ORG,
            "--description", "Handles checkout",
            "--tag", "team=backend",
            "--tag", "tier=1",
            "--dir", "/services",
            "--dir", "/apis",
            "--public-id", "checkout",
            "--message", "Add checkout service",
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output

    body = _body(sync)
    assert body.description == "Handles checkout"
    # Flat mapping on the way in; the backend nests it into {"value": ...} on
    # the way out, so request and response deliberately differ in shape.
    assert not isinstance(body.tags, Unset) and body.tags is not None
    assert body.tags.to_dict() == {"team": "backend", "tier": "1"}
    assert body.directories == ["/services", "/apis"]
    assert body.public_id == "checkout"
    assert body.commit_message == "Add checkout service"


@patch(_CREATE, return_value=_created())
@patch("yertle._client.get_client", return_value=object())
def test_create_prints_the_id_first(_client, _sync) -> None:
    """`NODE=$(yertle nodes create ... | head -1)` has to work."""
    result = runner.invoke(app, ["nodes", "create", "Checkout API", "--org", ORG])
    assert result.output.splitlines()[0] == "11111111-2222-3333-4444-555555555555"


@patch(_CREATE, return_value=_created())
@patch("yertle._client.get_client", return_value=object())
def test_create_says_where_the_unattached_node_shows_up(_client, _sync) -> None:
    """The notice must describe what actually happens, not just say "unattached".

    The first version of this line claimed the node would not appear in
    `nodes tree`. It does — the hierarchy endpoint treats a parentless node as
    a root — and the original test passed anyway, because it only looked for
    the word "Unattached". Pin the specific claim.
    """
    result = runner.invoke(app, ["nodes", "create", "Checkout API", "--org", ORG])
    plain = " ".join(result.output.split())
    assert "Unattached" in plain
    assert "as a root" in plain
    assert "not appear" not in plain


@patch(_CREATE, return_value=_created())
@patch("yertle._client.get_client", return_value=object())
def test_create_json_format_dumps_the_created_node(_client, _sync) -> None:
    result = runner.invoke(
        app, ["nodes", "create", "Checkout API", "--org", ORG, "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["id"] == "11111111-2222-3333-4444-555555555555"
    assert parsed["title"] == "Checkout API"


@patch(_CREATE, return_value=_created())
@patch("yertle._client.get_client", return_value=object())
def test_create_rejects_a_malformed_tag(_client, sync) -> None:
    result = runner.invoke(app, ["nodes", "create", "X", "--org", ORG, "--tag", "novalue"])
    assert result.exit_code == 1
    assert "--tag must be key=value" in result.output
    sync.assert_not_called()


@patch("yertle._client.get_client", return_value=object())
def test_create_refuses_to_guess_the_organization(_client) -> None:
    """Defaulting to 'all' is fine for a listing and wrong for a write."""
    result = runner.invoke(app, ["nodes", "create", "Checkout API"])
    assert result.exit_code == 1
    assert "needs one organization" in result.output
