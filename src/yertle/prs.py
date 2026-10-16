"""Pull requests resource. Imported as `yertle.prs`.

    >>> import yertle
    >>> for pr in yertle.prs.list(node_id, org_id=org_id):
    ...     print(pr.number, pr.title, pr.status)

Like branches, pull requests belong to a *node*: each node is its own little
repository, so PR numbers restart at 1 per node rather than being unique
across an organization. Every function here therefore takes both a node and
the org that owns it.

Module-as-namespace, following the shape `orgs.py` established.
"""

from __future__ import annotations

import builtins
from uuid import UUID

from yertle_client.api.pull_requests import (
    close_pull_request_orgs_org_id_nodes_node_id_pull_requests_pr_number_close_post as _close,
)
from yertle_client.api.pull_requests import (
    create_pull_request_orgs_org_id_nodes_node_id_pull_requests_post as _create,
)
from yertle_client.api.pull_requests import (
    get_pull_request_orgs_org_id_nodes_node_id_pull_requests_pr_number_get as _get,
)
from yertle_client.api.pull_requests import (
    list_pull_requests_orgs_org_id_nodes_node_id_pull_requests_get as _list,
)
from yertle_client.api.pull_requests import (
    merge_pull_request_orgs_org_id_nodes_node_id_pull_requests_pr_number_merge_post as _merge,
)
from yertle_client.models import (
    CreatePRRequest,
    CreatePRResponse,
    ListPRResponse,
    MergePRResponse,
    PRDetailResponse,
    PullRequestResponse,
)
from yertle_client.types import UNSET

from yertle._client import client
from yertle.nodes import DEFAULT_BRANCH

__all__ = ["close", "create", "get", "list", "merge"]


# `list` shadows the builtin inside this module — annotations reference
# `builtins.list` explicitly, exactly as `orgs.py` and `nodes.py` do.
def list(
    node_id: str,
    *,
    org_id: str,
    status: str | None = None,
) -> builtins.list[PullRequestResponse]:
    """List a node's pull requests, newest first.

    `status` filters to one of `open`, `merged` or `closed`; omitting it
    returns every state. The wire layer wraps the list in a
    `ListPRResponse(prs=[...], total_count=N)`; the envelope is unwrapped
    because `.total_count` is redundant with `len(...)`, matching
    `orgs.list()` and `branches.list()`.
    """
    response = _list.sync(
        client=client(),
        org_id=UUID(org_id),
        node_id=node_id,
        status=status if status is not None else UNSET,
    )
    if not isinstance(response, ListPRResponse):
        raise RuntimeError(f"Unexpected response from prs.list(): {response!r}")
    return response.prs


def get(number: int, *, node_id: str, org_id: str) -> PullRequestResponse:
    """Fetch one pull request by its per-node number.

    The detail response carries `can_merge` and `merge_reason`, which the
    list does not compute — so this is the call that answers "will this
    merge?" before you try.
    """
    response = _get.sync(client=client(), org_id=UUID(org_id), node_id=node_id, pr_number=number)
    if not isinstance(response, PRDetailResponse):
        raise RuntimeError(f"Unexpected response from prs.get({number}): {response!r}")
    return response.pr


def create(
    title: str,
    *,
    node_id: str,
    org_id: str,
    source_branch: str,
    target_branch: str = DEFAULT_BRANCH,
    description: str | None = None,
    draft: bool = False,
) -> PullRequestResponse:
    """Open a pull request from `source_branch` into `target_branch`."""
    response = _create.sync(
        client=client(),
        org_id=UUID(org_id),
        node_id=node_id,
        body=CreatePRRequest(
            title=title,
            source_branch=source_branch,
            target_branch=target_branch,
            description=description if description is not None else UNSET,
            is_draft=draft,
        ),
    )
    if not isinstance(response, CreatePRResponse):
        raise RuntimeError(f"Unexpected response from prs.create({title!r}): {response!r}")
    return response.pr


def merge(number: int, *, node_id: str, org_id: str) -> MergePRResponse:
    """Merge a pull request, returning the merge result.

    The response carries `merged` and `merge_commit` rather than the PR, so
    a caller that wants the PR's new state reads it back with `get()`.
    """
    response = _merge.sync(client=client(), org_id=UUID(org_id), node_id=node_id, pr_number=number)
    if not isinstance(response, MergePRResponse):
        raise RuntimeError(f"Unexpected response from prs.merge({number}): {response!r}")
    return response


def close(number: int, *, node_id: str, org_id: str) -> PullRequestResponse:
    """Close a pull request without merging it."""
    response = _close.sync(client=client(), org_id=UUID(org_id), node_id=node_id, pr_number=number)
    if not isinstance(response, PRDetailResponse):
        raise RuntimeError(f"Unexpected response from prs.close({number}): {response!r}")
    return response.pr
