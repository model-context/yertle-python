"""Tests for `yertle nodes search`.

Fixtures are captured from a real `POST /orgs/{id}/search/retrieve`. Two shapes
here differ from the endpoints the other commands use:

- `tags` are **flat** (`{"ARN": "arn:..."}`), where `/complete` nests them
  under `value`. Same concept, two wire shapes.
- `connections` arrive denormalised with `from_title` / `to_title`, so no id
  lookup is needed — unlike `/complete`'s internal connections.

`path` is only populated on expanded results, which is why the Path column is
conditional.
"""

import json
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from yertle_client.models import RetrieveResponse

from yertle.cli.main import app

runner = CliRunner()

ORG = "f586beac-7039-4f0c-9681-fd36293f071f"
_RETRIEVE = "yertle.search._retrieve.sync"

_FLAT: dict[str, Any] = {
    "query": "how do users reach the app",
    "matches": [
        {"node_id": "e4222c72", "title": "User", "score": 0.033, "match_reason": "hybrid"},
        {"node_id": "0cc209f2", "title": "API Gateway", "score": 0.016, "match_reason": "vector"},
    ],
    "nodes": [
        {
            "node_id": "e4222c72",
            "title": "User",
            "description": "",
            "path": [],
            "tags": {},
            "directories": [],
            "text_content": None,
        },
        {
            "node_id": "0cc209f2",
            "title": "API Gateway",
            "description": "HTTP API.",
            "path": [],
            "tags": {"ARN": "arn:aws:apigateway:us-east-1::/apis/rrqsqdvqe5"},
            "directories": [],
            "text_content": "Routes every public request.",
        },
    ],
    "connections": [],
}

_EXPANDED: dict[str, Any] = {
    **_FLAT,
    "nodes": [
        {**_FLAT["nodes"][0], "path": ["Root", "Yertle Webapp", "User"]},
        {**_FLAT["nodes"][1], "path": ["Root", "Yertle Webapp", "API Gateway"]},
    ],
    "connections": [
        {
            "connection_id": "638f13ef",
            "from_node_id": "e4222c72",
            "from_title": "User",
            "to_node_id": "0cc209f2",
            "to_title": "API Gateway",
            "label": None,
            "connection_type": "default",
        },
    ],
}


def _response(payload: dict[str, Any] | None = None) -> RetrieveResponse:
    return RetrieveResponse.from_dict(payload or _FLAT)


@pytest.fixture
def _default_org(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.setenv("YERTLE_ORG", ORG)


@patch(_RETRIEVE, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_search_ranks_matches(_get_client, _sync, _default_org) -> None:
    result = runner.invoke(app, ["nodes", "search", "how do users reach the app"])
    assert result.exit_code == 0, result.output
    assert "User" in result.output
    assert "API Gateway" in result.output
    assert "0.033" in result.output  # score, formatted
    assert "hybrid" in result.output  # match_reason


@patch(_RETRIEVE, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_search_hides_the_path_column_when_unexpanded(_get_client, _sync, _default_org) -> None:
    """The API only fills `path` on expanded results; a blank column is noise."""
    result = runner.invoke(app, ["nodes", "search", "q"])
    assert result.exit_code == 0, result.output
    assert "Path" not in result.output


@patch(_RETRIEVE, return_value=_response(_EXPANDED))
@patch("yertle._client.get_client", return_value=object())
def test_search_shows_paths_and_connections_when_expanded(_get_client, _sync, _default_org) -> None:
    result = runner.invoke(app, ["nodes", "search", "q", "--expand", "standard"])
    assert result.exit_code == 0, result.output
    assert "Path" in result.output
    assert "Connections" in result.output
    # A null label falls back to the connection type.
    assert "default" in result.output


@patch(_RETRIEVE, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_search_forwards_every_option(_get_client, sync, _default_org) -> None:
    result = runner.invoke(
        app,
        [
            "nodes",
            "search",
            "payments",
            "--top-k",
            "9",
            "--expand",
            "deep",
            "--tag",
            "team=platform",
            "--tag",
            "tier=1",
            "--scope-root",
            "root-id",
            "--dir-prefix",
            "/services",
        ],
    )
    assert result.exit_code == 0, result.output
    body = sync.call_args.kwargs["body"].to_dict()
    assert body["query"] == "payments"
    assert body["top_k"] == 9
    assert body["expansion_depth"] == "deep"
    assert body["scope"]["tag_filters"] == {"team": "platform", "tier": "1"}
    assert body["scope"]["root_node_id"] == "root-id"
    assert body["scope"]["directory_prefix"] == "/services"


@patch(_RETRIEVE, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_search_omits_scope_when_no_filters_given(_get_client, sync, _default_org) -> None:
    """An empty scope object would narrow nothing but is noise on the wire."""
    runner.invoke(app, ["nodes", "search", "q"])
    assert "scope" not in sync.call_args.kwargs["body"].to_dict()


@patch(_RETRIEVE, return_value=_response(_EXPANDED))
@patch("yertle._client.get_client", return_value=object())
def test_search_include_text_prints_prose(_get_client, _sync, _default_org) -> None:
    result = runner.invoke(app, ["nodes", "search", "q", "--include-text"])
    assert result.exit_code == 0, result.output
    assert "Routes every public request." in result.output


@patch(_RETRIEVE, return_value=_response({**_FLAT, "matches": [], "nodes": []}))
@patch("yertle._client.get_client", return_value=object())
def test_search_reports_no_matches_plainly(_get_client, _sync, _default_org) -> None:
    result = runner.invoke(app, ["nodes", "search", "nothing like this"])
    assert result.exit_code == 0, result.output
    assert "No matches" in result.output


@patch(_RETRIEVE, return_value=_response())
@patch("yertle._client.get_client", return_value=object())
def test_search_json_dumps_an_object(_get_client, _sync, _default_org) -> None:
    result = runner.invoke(app, ["nodes", "search", "q", "--format", "json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert isinstance(parsed, dict)
    assert [m["title"] for m in parsed["matches"]] == ["User", "API Gateway"]


@pytest.mark.parametrize("bad", ["nope", "=value", "  =x"])
def test_search_rejects_a_malformed_tag(bad: str, _default_org) -> None:
    """The message must not be followed by a second, wrong API error.

    `die()` raises `typer.Exit`, which subclasses RuntimeError — so before
    `api_errors()` re-raised it, this printed the real error and then
    "Unexpected response from the API".
    """
    result = runner.invoke(app, ["nodes", "search", "q", "--tag", bad])
    assert result.exit_code == 1
    assert "--tag must be key=value" in result.output
    assert "Unexpected response" not in result.output


def test_search_rejects_an_unknown_expansion(_default_org) -> None:
    result = runner.invoke(app, ["nodes", "search", "q", "--expand", "sideways"])
    assert result.exit_code != 0


def test_search_requires_a_single_org(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YERTLE_ORG", "all")
    result = runner.invoke(app, ["nodes", "search", "q"])
    assert result.exit_code == 1
    assert "needs one organization" in result.output
