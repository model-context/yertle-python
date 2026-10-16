"""Tests for `yertle nodes delete`.

Delete has no undo, so the tests that matter are the ones about *not*
deleting: that a pipe cannot be made to delete silently, that a refusal
from the backend is reported as a failure, and that the confirmation names
the node rather than showing a uuid nobody can check.

It is also a **soft** delete — history survives and parent canvases still
show the node — so the wording is pinned too. A flat "Deleted" would be
wrong in two senses, which is the same trap `nodes create` fell into with
`nodes tree`.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from yertle_client.models import Deleted, DeletionResultResponse, NodeTreeDocument

from tests._output import plain
from yertle.cli._context import ORG_ENV_VAR
from yertle.cli.main import app

runner = CliRunner()

ORG = "f586beac-7039-4f0c-9681-fd36293f071f"
NODE = "09b27471-7aa2-4ff2-8f4e-ca62941f06df"
_GET = "yertle.nodes._tree_document.sync"
_DELETE = "yertle.nodes.delete_node_orgs_org_id_nodes_node_id_delete.sync"
_FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_ambient_org(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.delenv(ORG_ENV_VAR, raising=False)


def _doc() -> NodeTreeDocument:
    raw = json.loads((_FIXTURES / "tree_document_rich.json").read_text())
    return NodeTreeDocument.from_dict(raw)


def _deleted(
    success: bool = True, message: str = "Node deleted successfully."
) -> DeletionResultResponse:
    return DeletionResultResponse(
        success=success,
        deleted=Deleted.from_dict({"node_id": NODE, "soft_deleted": True}),
        message=message,
    )


def _run(*extra: str, result: DeletionResultResponse | None = None, tty: bool = True):
    with (
        patch(_GET, return_value=_doc()),
        patch(_DELETE, return_value=result or _deleted()) as delete,
        patch("yertle._client.get_client", return_value=object()),
        patch("sys.stdin.isatty", return_value=tty),
    ):
        return runner.invoke(app, ["nodes", "delete", NODE, "--org", ORG, *extra]), delete


def test_names_the_node_before_deleting_it() -> None:
    """A uuid in a confirmation prompt is not something anyone can check."""
    result, _ = _run("--yes")
    assert result.exit_code == 0, result.output
    text = plain(result.output)
    assert "Yertle Webapp" in text
    assert "8 child(ren)" in text


def test_a_pipe_refuses_rather_than_hanging(tmp_path: Path) -> None:
    """Prompting with no terminal attached is the worst failure a CLI has.

    It waits forever on input that is never coming, which in an agent looks
    like the tool stopped responding.
    """
    result, delete = _run(tty=False)
    assert result.exit_code == 1
    assert "Refusing to delete without confirmation" in plain(result.output)
    delete.assert_not_called()


def test_yes_skips_the_prompt_in_a_pipe() -> None:
    result, delete = _run("--yes", tty=False)
    assert result.exit_code == 0, result.output
    delete.assert_called_once()


def test_declining_the_prompt_deletes_nothing() -> None:
    with (
        patch(_GET, return_value=_doc()),
        patch(_DELETE) as delete,
        patch("yertle._client.get_client", return_value=object()),
        patch("sys.stdin.isatty", return_value=True),
    ):
        result = runner.invoke(app, ["nodes", "delete", NODE, "--org", ORG], input="n\n")
    assert result.exit_code != 0
    delete.assert_not_called()


def test_says_soft_deleted_not_deleted() -> None:
    """History survives and parent canvases still show it.

    "Deleted" would be wrong in two senses, and this is exactly the trap
    `nodes create` fell into when it claimed an orphan would not appear in
    `nodes tree`.
    """
    result, _ = _run("--yes")
    text = plain(result.output)
    assert "Soft-deleted" in text
    assert "History is kept" in text


def test_an_unsuccessful_result_is_a_failure() -> None:
    """The endpoint reports success in the body; a false there is not a win."""
    result, _ = _run("--yes", result=_deleted(success=False, message="still attached"))
    assert result.exit_code == 1
    assert "Not deleted: still attached" in plain(result.output)


def test_refuses_to_guess_the_organization() -> None:
    with patch("yertle._client.get_client", return_value=object()):
        result = runner.invoke(app, ["nodes", "delete", NODE])
    assert result.exit_code == 1
    assert "needs one organization" in result.output


def test_validates_the_node_id() -> None:
    with patch("yertle._client.get_client", return_value=object()):
        result = runner.invoke(app, ["nodes", "delete", "not-a-uuid", "--org", ORG])
    assert result.exit_code == 1
    assert "is not a node id" in plain(result.output)
