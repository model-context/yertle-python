"""Tests for `yertle.nodes.document` and `yertle.nodes.push`.

The read-edit-push half of the SDK. Two things are worth pinning here and
neither is about happy-path plumbing:

- **Where a push goes** is derived from the document, not from the caller.
  Pushing document A at node B should be awkward, because push is a full
  replace and getting it wrong destroys the target's state.
- **The real payload parses.** `tree_document.json` is captured from prod,
  not written from memory — including a `node.metadata` polluted before
  yertle#377, which is what real nodes still look like.
"""

import json
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
from yertle_client.models import NodeTreeDocument, PushStateResponse, VisualProperty
from yertle_client.types import Unset

import yertle

ORG = "ed259eba-2e76-404f-a775-b17804216311"
NODE = "d5322260-1933-4d31-ab8c-6603ca707e8a"

_GET = "yertle.nodes._tree_document.sync"
_PUSH = "yertle.nodes._push.sync"

FIXTURE = Path(__file__).parent / "fixtures" / "tree_document.json"


def _document() -> NodeTreeDocument:
    """The captured prod document, parsed."""
    return NodeTreeDocument.from_dict(json.loads(FIXTURE.read_text()))


def _children(doc: NodeTreeDocument) -> list[VisualProperty]:
    """Narrow `visual_properties`, which the model types as `list | Unset`."""
    assert not isinstance(doc.state.visual_properties, Unset)
    return doc.state.visual_properties


def _pushed() -> PushStateResponse:
    return PushStateResponse(
        commit_id="c0ffee00-0000-0000-0000-000000000000",
        node_id=NODE,
        branch="main",
        message="x",
        objects_created=0,
        objects_reused=0,
        unchanged=True,
        ignored_keys=[],
    )


def test_the_captured_document_parses() -> None:
    """A fixture that does not match the wire is worse than no fixture."""
    doc = _document()
    assert doc.expected_head_commit
    assert doc.state.node.title == "Root"
    assert len(_children(doc)) == 4
    assert doc.status.counts.children == 4


def test_annotations_are_typed_fields_not_extras() -> None:
    """`_title` arrives as a declared field, so accessors are type-checked."""
    child = _children(_document())[0]
    assert child.field_title
    assert child.field_snapshot_commit_id


@patch(_GET, return_value=_document())
@patch("yertle._client.get_client", return_value=object())
def test_document_passes_the_org_as_a_uuid(_client, sync) -> None:
    yertle.nodes.document(NODE, org_id=ORG)
    assert sync.call_args.kwargs["org_id"] == UUID(ORG)
    assert sync.call_args.kwargs["node_id"] == NODE
    assert sync.call_args.kwargs["branch"] == "main"


@patch("yertle._client.get_client", return_value=object())
def test_document_rejects_all_orgs(_client) -> None:
    with pytest.raises(ValueError, match="not 'all'"):
        yertle.nodes.document(NODE, org_id=yertle.nodes.ALL_ORGS)


@patch(_GET, return_value=None)
@patch("yertle._client.get_client", return_value=object())
def test_document_raises_on_an_unexpected_response(_client, _sync) -> None:
    with pytest.raises(RuntimeError, match="Unexpected response"):
        yertle.nodes.document(NODE, org_id=ORG)


@patch(_PUSH, return_value=_pushed())
@patch("yertle._client.get_client", return_value=object())
def test_push_sends_the_document_where_it_came_from(_client, sync) -> None:
    """A document identifies its own node; the caller should not have to."""
    doc = _document()
    yertle.nodes.push(doc, message="edit")
    assert sync.call_args.kwargs["org_id"] == UUID(doc.status.org_id)
    assert sync.call_args.kwargs["node_id"] == doc.status.node_id
    assert sync.call_args.kwargs["branch"] == doc.status.branch


@patch(_PUSH, return_value=_pushed())
@patch("yertle._client.get_client", return_value=object())
def test_push_sends_the_documents_base_commit(_client, sync) -> None:
    """The concurrency token travels with the document, not the caller."""
    doc = _document()
    yertle.nodes.push(doc, message="edit")
    body = sync.call_args.kwargs["body"]
    assert body.expected_head_commit == doc.expected_head_commit
    assert body.message == "edit"
    assert body.state is doc.state


@patch(_PUSH, return_value=_pushed())
@patch("yertle._client.get_client", return_value=object())
def test_push_overrides_win(_client, sync) -> None:
    """The escape hatch: rebase onto a head you did not read, or fork a branch."""
    yertle.nodes.push(
        _document(),
        message="rebased",
        branch="feature",
        expected_head_commit="deadbeef-0000-0000-0000-000000000000",
    )
    assert sync.call_args.kwargs["branch"] == "feature"
    assert sync.call_args.kwargs["body"].expected_head_commit.startswith("deadbeef")


@patch(_PUSH)
@patch("yertle._client.get_client", return_value=object())
def test_push_refuses_a_document_that_names_no_target(_client, sync) -> None:
    """Better a clear error than a 404 from a request built out of blanks."""
    doc = _document()
    doc.status.org_id = ""
    with pytest.raises(ValueError, match="could not tell which node"):
        yertle.nodes.push(doc, message="x")
    sync.assert_not_called()


@patch(_PUSH, return_value=None)
@patch("yertle._client.get_client", return_value=object())
def test_push_raises_on_an_unexpected_response(_client, _sync) -> None:
    with pytest.raises(RuntimeError, match="Unexpected response"):
        yertle.nodes.push(_document(), message="x")
