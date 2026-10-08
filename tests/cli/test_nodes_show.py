"""Tests for `yertle nodes show`.

Both fixtures are **captures** from prod, not hand-written approximations,
because inventing them is what let the `nodes tree` path bug ship green.
Two documents rather than one, since no single real node exercises every
section:

- `tree_document_rich.json` — "Yertle Webapp": 8 children, 6 connections
  between them, 1 parent.
- `tree_document_boundary.json` — "CloudFront": a leaf with ingress and
  egress, which is the only way to cover the boundary section.

Shapes in here that would have been guessed wrong:

- children live in `state.visual_properties`, keyed by `child_node_id`,
  with the title as a `_title` annotation — not in a `child_nodes` list;
- parents live in `status`, not `state`, because the containment edge is
  stored in the *parent's* canvas;
- `status.ingress` / `.egress` arrive denormalised with `connected_node`
  attached, and their `label` is routinely null.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from yertle_client.models import NodeTreeDocument

from tests._output import plain
from yertle.cli._context import ORG_ENV_VAR
from yertle.cli.main import app

runner = CliRunner()

ORG = "f586beac-7039-4f0c-9681-fd36293f071f"
NODE = "09b27471-7aa2-4ff2-8f4e-ca62941f06df"
_GET = "yertle.nodes._tree_document.sync"
_FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_ambient_org(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.delenv(ORG_ENV_VAR, raising=False)


def _doc(name: str = "tree_document_rich") -> NodeTreeDocument:
    return NodeTreeDocument.from_dict(json.loads((_FIXTURES / f"{name}.json").read_text()))


def _show(*extra: str, fixture: str = "tree_document_rich"):
    with (
        patch(_GET, return_value=_doc(fixture)),
        patch("yertle._client.get_client", return_value=object()),
    ):
        return runner.invoke(app, ["nodes", "show", NODE, "--org", ORG, *extra])


def test_show_renders_the_header() -> None:
    result = _show()
    assert result.exit_code == 0, result.output
    text = plain(result.output)
    assert "Yertle Webapp" in text
    # The id comes from `status`, not from `state.node` — the write document
    # carries no id, because push does not store one.
    assert NODE in text
    assert "branch main" in text


def test_show_renders_tags_and_directories() -> None:
    text = plain(_show().output)
    assert "Tags" in text
    assert "Team" in text


def test_show_lists_children_from_visual_properties() -> None:
    """Children are positions on this node's canvas, titled by annotation."""
    text = plain(_show().output)
    assert "Children (8)" in text
    titles = [
        vp["_title"]
        for vp in json.loads((_FIXTURES / "tree_document_rich.json").read_text())["state"][
            "visual_properties"
        ]
    ]
    for title in titles:
        assert title in text, f"missing child {title}"


def test_show_names_both_ends_of_a_connection() -> None:
    """`_from_title` / `_to_title` make the id-to-title lookup unnecessary."""
    text = plain(_show().output)
    assert "Connections between children (6)" in text
    assert "→" in text
    # A bare uuid in this section means an annotation was missing and the
    # accessor fell back to the id.
    assert "from_child_id" not in text


def test_show_lists_parents_from_status() -> None:
    text = plain(_show().output)
    assert "Parents (1)" in text


def test_show_renders_the_boundary_sections() -> None:
    """Only a node with cross-boundary edges exercises these."""
    text = plain(_show(fixture="tree_document_boundary").output)
    assert "Ingress (1)" in text
    assert "User → this" in text
    assert "Egress (1)" in text
    assert "this → S3 Bucket" in text


def test_show_omits_empty_sections() -> None:
    """A leaf should read as a short page, not a form full of blanks."""
    text = plain(_show(fixture="tree_document_boundary").output)
    assert "Children" not in text
    assert "Connections between children" not in text


def test_show_json_dumps_the_whole_document() -> None:
    """JSON must stay the full document, so it can be edited and pushed back."""
    result = _show("--format", "json")
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["expected_head_commit"]
    assert sorted(parsed["state"]) == [
        "connections",
        "directories",
        "node",
        "tags",
        "visual_properties",
    ]


def test_show_passes_the_branch_through() -> None:
    with (
        patch(_GET, return_value=_doc()) as sync,
        patch("yertle._client.get_client", return_value=object()),
    ):
        runner.invoke(app, ["nodes", "show", NODE, "--org", ORG, "--branch", "feature-x"])
    assert sync.call_args.kwargs["branch"] == "feature-x"


def test_show_refuses_to_guess_the_organization() -> None:
    with patch("yertle._client.get_client", return_value=object()):
        result = runner.invoke(app, ["nodes", "show", NODE])
    assert result.exit_code == 1
    assert "needs one organization" in result.output
