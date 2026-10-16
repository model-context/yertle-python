"""Tests for `yertle.prs`.

Pull requests are per-node, like branches, so what matters here is that both
identifiers reach the wire and that the envelopes are unwrapped the way the
rest of the SDK does it. `merge` is the exception: it returns the merge
result rather than the PR, and that difference is deliberate.
"""

import datetime
from unittest.mock import patch
from uuid import UUID

import pytest
from yertle_client.models import (
    CreatePRResponse,
    ListPRResponse,
    MergePRResponse,
    PRDetailResponse,
    PullRequestResponse,
)
from yertle_client.types import UNSET

import yertle

ORG = "8f14e45f-ceea-467a-9575-28db8d0dc4db"
NODE = "11111111-2222-3333-4444-555555555555"

_LIST = "yertle.prs._list.sync"
_GET = "yertle.prs._get.sync"
_CREATE = "yertle.prs._create.sync"
_MERGE = "yertle.prs._merge.sync"
_CLOSE = "yertle.prs._close.sync"


def _pr(number: int = 1, status: str = "open") -> PullRequestResponse:
    now = datetime.datetime(2026, 10, 16, tzinfo=datetime.UTC)
    return PullRequestResponse(
        id="pr-1",
        node_id=NODE,
        number=number,
        title="Add the payments subtree",
        source_branch="feature-x",
        target_branch="main",
        source_commit="aaaa",
        target_commit="bbbb",
        status=status,
        is_draft=False,
        author="someone",
        created_at=now,
        updated_at=now,
    )


@patch(_LIST, return_value=ListPRResponse(prs=[_pr(1), _pr(2)], total_count=2))
@patch("yertle._client.get_client", return_value=object())
def test_list_unwraps_the_envelope(_client, sync) -> None:
    prs = yertle.prs.list(NODE, org_id=ORG)
    assert [p.number for p in prs] == [1, 2]
    assert sync.call_args.kwargs["org_id"] == UUID(ORG)
    assert sync.call_args.kwargs["node_id"] == NODE
    # No filter requested means no filter sent — not an empty one.
    assert sync.call_args.kwargs["status"] is UNSET


@patch(_LIST, return_value=ListPRResponse(prs=[], total_count=0))
@patch("yertle._client.get_client", return_value=object())
def test_list_forwards_a_status_filter(_client, sync) -> None:
    yertle.prs.list(NODE, org_id=ORG, status="merged")
    assert sync.call_args.kwargs["status"] == "merged"


@patch(_GET, return_value=PRDetailResponse(pr=_pr()))
@patch("yertle._client.get_client", return_value=object())
def test_get_unwraps_the_detail(_client, sync) -> None:
    pr = yertle.prs.get(1, node_id=NODE, org_id=ORG)
    assert pr.number == 1
    assert sync.call_args.kwargs["pr_number"] == 1


@patch(_CREATE, return_value=CreatePRResponse(pr=_pr()))
@patch("yertle._client.get_client", return_value=object())
def test_create_defaults_to_targeting_main(_client, sync) -> None:
    yertle.prs.create("t", node_id=NODE, org_id=ORG, source_branch="feature-x")
    body = sync.call_args.kwargs["body"]
    assert body.source_branch == "feature-x"
    assert body.target_branch == "main"
    assert body.is_draft is False
    assert body.description is UNSET


@patch(_CREATE, return_value=CreatePRResponse(pr=_pr()))
@patch("yertle._client.get_client", return_value=object())
def test_create_forwards_everything_it_is_given(_client, sync) -> None:
    yertle.prs.create(
        "t",
        node_id=NODE,
        org_id=ORG,
        source_branch="feature-x",
        target_branch="develop",
        description="why",
        draft=True,
    )
    body = sync.call_args.kwargs["body"]
    assert (body.target_branch, body.description, body.is_draft) == ("develop", "why", True)


@patch(_MERGE, return_value=MergePRResponse(merged=True, merge_commit="cccc"))
@patch("yertle._client.get_client", return_value=object())
def test_merge_returns_the_result_not_the_pr(_client, _sync) -> None:
    """The endpoint answers "did it merge", not "what is the PR now"."""
    result = yertle.prs.merge(1, node_id=NODE, org_id=ORG)
    assert result.merged is True
    assert result.merge_commit == "cccc"


@patch(_CLOSE, return_value=PRDetailResponse(pr=_pr(status="closed")))
@patch("yertle._client.get_client", return_value=object())
def test_close_returns_the_closed_pr(_client, _sync) -> None:
    assert yertle.prs.close(1, node_id=NODE, org_id=ORG).status == "closed"


@pytest.mark.parametrize(
    ("target", "call"),
    [
        (_LIST, lambda: yertle.prs.list(NODE, org_id=ORG)),
        (_GET, lambda: yertle.prs.get(1, node_id=NODE, org_id=ORG)),
        (_CREATE, lambda: yertle.prs.create("t", node_id=NODE, org_id=ORG, source_branch="b")),
        (_MERGE, lambda: yertle.prs.merge(1, node_id=NODE, org_id=ORG)),
        (_CLOSE, lambda: yertle.prs.close(1, node_id=NODE, org_id=ORG)),
    ],
)
@patch("yertle._client.get_client", return_value=object())
def test_unexpected_responses_raise(_client, target, call) -> None:
    with patch(target, return_value=None), pytest.raises(RuntimeError, match="Unexpected response"):
        call()
