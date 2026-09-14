"""Tests for `yertle.search`."""

from unittest.mock import patch

import pytest
from yertle_client.models import RetrieveResponse

import yertle

ORG = "8f14e45f-ceea-467a-9575-28db8d0dc4db"
_RETRIEVE = "yertle.search._retrieve.sync"


def _response() -> RetrieveResponse:
    return RetrieveResponse.from_dict(
        {"query": "q", "matches": [], "nodes": [], "connections": []},
    )


@patch(_RETRIEVE, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_retrieve_omits_expansion_by_default(_get_client, sync) -> None:
    """No depth sent means the server applies its own default, not ours."""
    yertle.search.retrieve("q", org_id=ORG)
    assert "expansion_depth" not in sync.call_args.kwargs["body"].to_dict()


@patch(_RETRIEVE, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_retrieve_sends_an_explicit_expansion(_get_client, sync) -> None:
    yertle.search.retrieve("q", org_id=ORG, expansion=yertle.search.Expansion.DEEP)
    assert sync.call_args.kwargs["body"].to_dict()["expansion_depth"] == "deep"


def test_retrieve_refuses_all_orgs() -> None:
    """Retrieval ranks within one graph; 'all' has no meaning here."""
    with pytest.raises(ValueError, match="specific org_id"):
        yertle.search.retrieve("q", org_id="all")


@patch(_RETRIEVE, return_value=None)
@patch("yertle._client.get_client", return_value=object())
def test_retrieve_raises_on_an_unexpected_response(_get_client, _sync) -> None:
    with pytest.raises(RuntimeError, match="Unexpected response"):
        yertle.search.retrieve("q", org_id=ORG)
