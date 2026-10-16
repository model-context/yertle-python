"""Tests for the `yertle prs` command group.

Mocks the wire layer, so these exercise the real CLI -> `yertle.prs` ->
`yertle_client` path. Two things are worth pinning beyond plumbing: that
`show` explains *why* a PR cannot merge rather than printing a bare false,
and that a merge the backend declined is reported as a failure rather than
as success.
"""

import datetime
import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from yertle_client.models import (
    CreatePRResponse,
    ListPRResponse,
    MergePRResponse,
    PRDetailResponse,
    PullRequestResponse,
)

from tests._output import plain
from yertle.cli._context import ORG_ENV_VAR
from yertle.cli.main import app

runner = CliRunner()

ORG = "8f14e45f-ceea-467a-9575-28db8d0dc4db"
NODE = "11111111-2222-3333-4444-555555555555"
_LIST = "yertle.prs._list.sync"
_GET = "yertle.prs._get.sync"
_CREATE = "yertle.prs._create.sync"
_MERGE = "yertle.prs._merge.sync"
_CLOSE = "yertle.prs._close.sync"


@pytest.fixture(autouse=True)
def _no_ambient_org(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.delenv(ORG_ENV_VAR, raising=False)


def _pr(
    number: int = 1,
    *,
    status: str = "open",
    draft: bool = False,
    can_merge: bool | None = None,
    reason: str | None = None,
) -> PullRequestResponse:
    now = datetime.datetime(2026, 10, 16, tzinfo=datetime.UTC)
    pr = PullRequestResponse(
        id="pr-1",
        node_id=NODE,
        number=number,
        title="Add the payments subtree",
        source_branch="feature-x",
        target_branch="main",
        source_commit="aaaa",
        target_commit="bbbb",
        status=status,
        is_draft=draft,
        author="someone",
        created_at=now,
        updated_at=now,
    )
    if can_merge is not None:
        pr.can_merge = can_merge
    if reason is not None:
        pr.merge_reason = reason
    return pr


@patch(_LIST, return_value=ListPRResponse(prs=[_pr(1), _pr(2, status="merged")], total_count=2))
@patch("yertle._client.get_client", return_value=object())
def test_list_shows_number_status_and_branches(_client, _sync) -> None:
    result = runner.invoke(app, ["prs", "list", NODE, "--org", ORG], terminal_width=200)
    assert result.exit_code == 0, result.output
    text = plain(result.output)
    assert "1 Add the payments subtree open feature-x → main" in text
    assert "merged" in text


@patch(_LIST, return_value=ListPRResponse(prs=[_pr(1, draft=True)], total_count=1))
@patch("yertle._client.get_client", return_value=object())
def test_list_calls_out_drafts(_client, _sync) -> None:
    """An open draft is not ready to merge, and the status alone hides that."""
    result = runner.invoke(app, ["prs", "list", NODE, "--org", ORG], terminal_width=200)
    assert "(draft)" in plain(result.output)


@patch(_LIST, return_value=ListPRResponse(prs=[], total_count=0))
@patch("yertle._client.get_client", return_value=object())
def test_list_forwards_the_status_filter(_client, sync) -> None:
    runner.invoke(app, ["prs", "list", NODE, "--org", ORG, "--status", "open"])
    assert sync.call_args.kwargs["status"] == "open"


@patch(_GET, return_value=PRDetailResponse(pr=_pr(can_merge=False, reason="branch has conflicts")))
@patch("yertle._client.get_client", return_value=object())
def test_show_explains_why_a_pr_cannot_merge(_client, _sync) -> None:
    """`can_merge: false` alone is the least useful true thing to print."""
    result = runner.invoke(app, ["prs", "show", NODE, "1", "--org", ORG], terminal_width=200)
    assert result.exit_code == 0, result.output
    assert "no — branch has conflicts" in plain(result.output)


@patch(_GET, return_value=PRDetailResponse(pr=_pr(can_merge=True)))
@patch("yertle._client.get_client", return_value=object())
def test_show_reports_a_mergeable_pr(_client, _sync) -> None:
    result = runner.invoke(app, ["prs", "show", NODE, "1", "--org", ORG], terminal_width=200)
    assert "Can merge yes" in plain(result.output)


@patch(_GET, return_value=PRDetailResponse(pr=_pr()))
@patch("yertle._client.get_client", return_value=object())
def test_show_json_dumps_the_pr(_client, _sync) -> None:
    result = runner.invoke(app, ["prs", "show", NODE, "1", "--org", ORG, "--format", "json"])
    assert json.loads(result.output)["number"] == 1


@patch(_CREATE, return_value=CreatePRResponse(pr=_pr(7)))
@patch("yertle._client.get_client", return_value=object())
def test_create_prints_the_number_first(_client, _sync) -> None:
    """Every other verb takes the number, so `$(... | head -1)` must give it."""
    result = runner.invoke(
        app, ["prs", "create", NODE, "Title", "--org", ORG, "--source", "feature-x"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0] == "7"


@patch(_CREATE)
@patch("yertle._client.get_client", return_value=object())
def test_create_requires_a_source_branch(_client, sync) -> None:
    """There is no sensible default: it is the whole point of the PR."""
    result = runner.invoke(app, ["prs", "create", NODE, "Title", "--org", ORG])
    assert result.exit_code == 1
    assert "needs a source branch" in plain(result.output)
    sync.assert_not_called()


@patch(_MERGE, return_value=MergePRResponse(merged=True, merge_commit="cccc"))
@patch("yertle._client.get_client", return_value=object())
def test_merge_reports_the_merge_commit(_client, _sync) -> None:
    result = runner.invoke(app, ["prs", "merge", NODE, "1", "--org", ORG])
    assert result.exit_code == 0, result.output
    text = plain(result.output)
    assert "Merged #1" in text
    assert "cccc" in text


@patch(_MERGE, return_value=MergePRResponse(merged=False, merge_commit=""))
@patch("yertle._client.get_client", return_value=object())
def test_a_declined_merge_is_a_failure(_client, _sync) -> None:
    """The endpoint can answer 200 with merged=false; that is not success.

    `merge_commit` is a required `str` in the schema even here, so the
    declined case arrives as an empty string rather than a null.
    """
    result = runner.invoke(app, ["prs", "merge", NODE, "1", "--org", ORG])
    assert result.exit_code == 1
    assert "was not merged" in plain(result.output)


@patch(_CLOSE, return_value=PRDetailResponse(pr=_pr(status="closed")))
@patch("yertle._client.get_client", return_value=object())
def test_close_confirms_by_number_and_title(_client, _sync) -> None:
    result = runner.invoke(app, ["prs", "close", NODE, "1", "--org", ORG])
    assert result.exit_code == 0, result.output
    assert "Closed #1 Add the payments subtree" in plain(result.output)


@patch("yertle._client.get_client", return_value=object())
def test_every_verb_validates_the_node_id(_client) -> None:
    for argv in (
        ["prs", "list", "not-a-uuid"],
        ["prs", "show", "not-a-uuid", "1"],
        ["prs", "create", "not-a-uuid", "t", "--source", "b"],
        ["prs", "merge", "not-a-uuid", "1"],
        ["prs", "close", "not-a-uuid", "1"],
    ):
        result = runner.invoke(app, [*argv, "--org", ORG])
        assert result.exit_code == 1, argv
        assert "is not a node id" in plain(result.output), argv
