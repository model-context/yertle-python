"""Tests for `yertle.branches`.

Branches are per-node, so the thing worth pinning down is that both the node
and the org reach the wire layer — and that `delete` defaults to the safe
form rather than the destructive one.
"""

import datetime
from unittest.mock import patch

import pytest
from yertle_client.models import (
    BranchListResponse,
    BranchResponse,
    MessageResponse,
)

import yertle

ORG = "8f14e45f-ceea-467a-9575-28db8d0dc4db"
NODE = "11111111-2222-3333-4444-555555555555"

_LIST = "yertle.branches.list_branches_orgs_org_id_nodes_node_id_branches_get.sync"
_CREATE = "yertle.branches.create_branch_orgs_org_id_nodes_node_id_branches_post.sync"
_DELETE = "yertle.branches.delete_branch_orgs_org_id_nodes_node_id_branches_branch_name_delete.sync"


def _branch(name: str = "main") -> BranchResponse:
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    return BranchResponse(
        node_id=NODE,
        name=name,
        head_commit="a64edca5-a874-4255-a22b-4066712d89ee",
        created_by="someone",
        created_at=now,
        updated_at=now,
    )


@patch(_LIST, return_value=BranchListResponse(branches=[_branch(), _branch("feature")], total=2))
@patch("yertle._client.get_client", return_value=object())
def test_list_unwraps_the_envelope(_get_client, sync) -> None:
    branches = yertle.branches.list(NODE, org_id=ORG)
    assert [b.name for b in branches] == ["main", "feature"]
    assert sync.call_args.kwargs["node_id"] == NODE
    assert sync.call_args.kwargs["org_id"] == ORG


@patch(_CREATE, return_value=_branch("feature"))
@patch("yertle._client.get_client", return_value=object())
def test_create_defaults_to_forking_main(_get_client, sync) -> None:
    yertle.branches.create("feature", node_id=NODE, org_id=ORG)
    assert sync.call_args.kwargs["body"].base_branch == "main"


@patch(_CREATE, return_value=_branch("feature"))
@patch("yertle._client.get_client", return_value=object())
def test_create_honours_an_explicit_base(_get_client, sync) -> None:
    yertle.branches.create("hotfix", node_id=NODE, org_id=ORG, base_branch="feature")
    assert sync.call_args.kwargs["body"].base_branch == "feature"


@patch(_DELETE, return_value=MessageResponse(message="Branch deleted"))
@patch("yertle._client.get_client", return_value=object())
def test_delete_is_safe_by_default(_get_client, sync) -> None:
    """`force` must default to False — this is `git branch -d`, not `-D`."""
    message = yertle.branches.delete("feature", node_id=NODE, org_id=ORG)
    assert message == "Branch deleted"
    assert sync.call_args.kwargs["force"] is False


@patch(_DELETE, return_value=MessageResponse(message="Branch force deleted"))
@patch("yertle._client.get_client", return_value=object())
def test_delete_forwards_force(_get_client, sync) -> None:
    yertle.branches.delete("feature", node_id=NODE, org_id=ORG, force=True)
    assert sync.call_args.kwargs["force"] is True


@pytest.mark.parametrize(
    ("target", "call"),
    [
        (_LIST, lambda: yertle.branches.list(NODE, org_id=ORG)),
        (_CREATE, lambda: yertle.branches.create("x", node_id=NODE, org_id=ORG)),
        (_DELETE, lambda: yertle.branches.delete("x", node_id=NODE, org_id=ORG)),
    ],
)
@patch("yertle._client.get_client", return_value=object())
def test_unexpected_responses_raise(_get_client, target, call) -> None:
    """A 422 body arrives where a model was expected; that is not a result."""
    with patch(target, return_value=None), pytest.raises(RuntimeError, match="Unexpected response"):
        call()
