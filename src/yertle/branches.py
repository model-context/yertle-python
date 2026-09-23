"""Branches resource. Imported as `yertle.branches`.

    >>> import yertle
    >>> for branch in yertle.branches.list(node_id, org_id=org_id):
    ...     print(branch.name, branch.head_commit)

Branches are per *node*, not per organization: each node carries its own
`main` plus whatever feature branches exist on it, the way a repository
carries its own. Every function here therefore takes both a node and the org
that owns it.

Module-as-namespace, following the shape `orgs.py` established.
"""

from __future__ import annotations

import builtins

from yertle_client.api.branches import (
    create_branch_orgs_org_id_nodes_node_id_branches_post,
    delete_branch_orgs_org_id_nodes_node_id_branches_branch_name_delete,
    list_branches_orgs_org_id_nodes_node_id_branches_get,
)
from yertle_client.models import (
    BranchListResponse,
    BranchResponse,
    CreateBranchRequest,
    MessageResponse,
)

from yertle._client import client
from yertle.nodes import DEFAULT_BRANCH

__all__ = ["DEFAULT_BRANCH", "create", "delete", "list"]

# Unlike the node and org endpoints, these take `org_id` as a plain string in
# the generated signature rather than a UUID. Passing a `UUID` here would be
# the mistyped-parameter mistake `nodes._fetch_page` documents in reverse, so
# the strings are passed through untouched.


# `list` shadows the builtin inside this module — annotations reference
# `builtins.list` explicitly, exactly as `orgs.py` and `nodes.py` do.
def list(node_id: str, *, org_id: str) -> builtins.list[BranchResponse]:
    """List the branches on one node.

    The wire layer returns `BranchListResponse(branches=[...], total=N)`; the
    envelope is unwrapped because `.total` is redundant with `len(...)` for
    SDK callers, matching `orgs.list()`.

    Every node has at least `main`, created with the node itself, so an empty
    list means the node does not exist rather than that it has no branches.
    """
    response = list_branches_orgs_org_id_nodes_node_id_branches_get.sync(
        client=client(),
        org_id=org_id,
        node_id=node_id,
    )
    if not isinstance(response, BranchListResponse):
        raise RuntimeError(f"Unexpected response from branches.list(): {response!r}")
    return response.branches


def create(
    name: str,
    *,
    node_id: str,
    org_id: str,
    base_branch: str = DEFAULT_BRANCH,
) -> BranchResponse:
    """Create a branch on `node_id`, forked from `base_branch`.

    The new branch starts at the base's head commit, so it is identical to
    the base until something is pushed to it — the same as `git branch`.
    """
    response = create_branch_orgs_org_id_nodes_node_id_branches_post.sync(
        client=client(),
        org_id=org_id,
        node_id=node_id,
        body=CreateBranchRequest(name=name, base_branch=base_branch),
    )
    if not isinstance(response, BranchResponse):
        raise RuntimeError(f"Unexpected response from branches.create({name!r}): {response!r}")
    return response


def delete(name: str, *, node_id: str, org_id: str, force: bool = False) -> str:
    """Delete a branch, returning the backend's confirmation message.

    **This is not `git branch -d`.** `force` gates one thing only: whether
    the branch has **open pull requests**. `BranchService.delete_branch`
    checks `get_open_prs_for_branch` and nothing else — there is no
    merged-into-main check anywhere in the path.

    So a branch carrying commits that exist nowhere else is deleted without
    complaint, and those commits become unreachable. Verified against prod
    2026-09-23: a branch whose head had diverged from main deleted cleanly
    with `force=False`.

    The route's own docstring says deletion requires the branch to be merged.
    It does not. Treat every delete here as destructive.

    `main` cannot be deleted. Deleting a branch requires editor or owner on
    the organization; viewers get a 403.
    """
    response = delete_branch_orgs_org_id_nodes_node_id_branches_branch_name_delete.sync(
        client=client(),
        org_id=org_id,
        node_id=node_id,
        branch_name=name,
        force=force,
    )
    if not isinstance(response, MessageResponse):
        raise RuntimeError(f"Unexpected response from branches.delete({name!r}): {response!r}")
    return response.message
