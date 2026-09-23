"""Tests for the `yertle branches` command group.

Mocks the wire layer, so these exercise the real
CLI -> `yertle.branches` -> `yertle_client` path.
"""

import datetime
import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from yertle_client.models import BranchListResponse, BranchResponse, MessageResponse

from tests._output import plain
from yertle.cli._context import ORG_ENV_VAR
from yertle.cli.main import app

runner = CliRunner()

ORG = "8f14e45f-ceea-467a-9575-28db8d0dc4db"
NODE = "11111111-2222-3333-4444-555555555555"

_LIST = "yertle.branches.list_branches_orgs_org_id_nodes_node_id_branches_get.sync"
_CREATE = "yertle.branches.create_branch_orgs_org_id_nodes_node_id_branches_post.sync"
_DELETE = "yertle.branches.delete_branch_orgs_org_id_nodes_node_id_branches_branch_name_delete.sync"


@pytest.fixture(autouse=True)
def _no_ambient_org(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.delenv(ORG_ENV_VAR, raising=False)


def _branch(name: str = "main", *, base: str | None = None, message: str | None = None):
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    kwargs = {}
    if base is not None:
        kwargs["base_branch"] = base
    if message is not None:
        kwargs["head_commit_message"] = message
    return BranchResponse(
        node_id=NODE,
        name=name,
        head_commit="a64edca5-a874-4255-a22b-4066712d89ee",
        created_by="someone",
        created_at=now,
        updated_at=now,
        **kwargs,
    )


def _listing() -> BranchListResponse:
    return BranchListResponse(
        branches=[
            _branch(),
            _branch("feature", base="main", message="Attach the payments subtree"),
        ],
        total=2,
    )


@patch(_LIST, return_value=_listing())
@patch("yertle._client.get_client", return_value=object())
def test_list_shows_branches(_client, _sync) -> None:
    result = runner.invoke(app, ["branches", "list", NODE, "--org", ORG], terminal_width=200)
    assert result.exit_code == 0, result.output
    text = plain(result.output)
    assert "Branches on" in text
    # Head commit is abbreviated the way git does in a listing.
    assert "feature a64edca5 main Attach the payments subtree" in text


@patch(_LIST, return_value=_listing())
@patch("yertle._client.get_client", return_value=object())
def test_list_json_keeps_the_full_commit(_client, _sync) -> None:
    """The table abbreviates; JSON must not, or the id cannot be passed back."""
    result = runner.invoke(app, ["branches", "list", NODE, "--org", ORG, "--format", "json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed[0]["head_commit"] == "a64edca5-a874-4255-a22b-4066712d89ee"


@patch(_LIST, return_value=BranchListResponse(branches=[_branch()], total=1))
@patch("yertle._client.get_client", return_value=object())
def test_list_shows_a_dash_for_fields_the_backend_left_unset(_client, _sync) -> None:
    result = runner.invoke(app, ["branches", "list", NODE, "--org", ORG], terminal_width=200)
    assert "—" in result.output


@patch(_CREATE, return_value=_branch("feature"))
@patch("yertle._client.get_client", return_value=object())
def test_create_defaults_to_main_as_the_base(_client, sync) -> None:
    result = runner.invoke(app, ["branches", "create", NODE, "feature", "--org", ORG])
    assert result.exit_code == 0, result.output
    assert sync.call_args.kwargs["body"].base_branch == "main"
    assert "Created branch" in plain(result.output)


@patch(_CREATE, return_value=_branch("hotfix"))
@patch("yertle._client.get_client", return_value=object())
def test_create_accepts_another_base(_client, sync) -> None:
    result = runner.invoke(
        app, ["branches", "create", NODE, "hotfix", "--org", ORG, "--base", "feature"]
    )
    assert result.exit_code == 0, result.output
    assert sync.call_args.kwargs["body"].base_branch == "feature"


@patch(_DELETE, return_value=MessageResponse(message="Branch 'feature' deleted"))
@patch("yertle._client.get_client", return_value=object())
def test_delete_does_not_force_unless_asked(_client, sync) -> None:
    """`force` must be opt-in.

    Note what it actually gates: open pull requests, not merge status. The
    backend performs no merged-into-main check, so the bare form is still
    destructive — see `yertle.branches.delete`.
    """
    result = runner.invoke(app, ["branches", "delete", NODE, "feature", "--org", ORG])
    assert result.exit_code == 0, result.output
    assert sync.call_args.kwargs["force"] is False


@patch(_DELETE, return_value=MessageResponse(message="Branch 'feature' deleted"))
@patch("yertle._client.get_client", return_value=object())
def test_delete_forwards_force(_client, sync) -> None:
    result = runner.invoke(app, ["branches", "delete", NODE, "feature", "--org", ORG, "--force"])
    assert result.exit_code == 0, result.output
    assert sync.call_args.kwargs["force"] is True


@patch("yertle._client.get_client", return_value=object())
def test_branch_commands_refuse_to_guess_the_organization(_client) -> None:
    for argv in (
        ["branches", "list", NODE],
        ["branches", "create", NODE, "feature"],
        ["branches", "delete", NODE, "feature"],
    ):
        result = runner.invoke(app, argv)
        assert result.exit_code == 1, argv
        assert "needs one organization" in result.output


@patch(_DELETE)
@patch(_LIST)
@patch("yertle._client.get_client", return_value=object())
def test_a_malformed_node_id_never_reaches_the_wire(_client, list_sync, delete_sync) -> None:
    """Catch a bad id locally instead of relaying `400 badly formed ... UUID`.

    That backend message does not say which id was wrong — a branch command
    sends two — and reads like a server fault rather than a typo. The real
    way this happens is a truncated copy-paste, so the length is named.
    """
    truncated = NODE[:-1]
    result = runner.invoke(app, ["branches", "delete", truncated, "feature", "--org", ORG])
    assert result.exit_code == 1
    plain_out = plain(result.output)
    assert "is not a node id" in plain_out
    assert "35 characters" in plain_out
    delete_sync.assert_not_called()
    list_sync.assert_not_called()


@patch(_LIST, return_value=_listing())
@patch("yertle._client.get_client", return_value=object())
def test_node_id_is_validated_on_every_verb(_client, _sync) -> None:
    for argv in (
        ["branches", "list", "not-a-uuid", "--org", ORG],
        ["branches", "create", "not-a-uuid", "feature", "--org", ORG],
        ["branches", "delete", "not-a-uuid", "feature", "--org", ORG],
    ):
        result = runner.invoke(app, argv)
        assert result.exit_code == 1, argv
        assert "is not a node id" in plain(result.output), argv
