"""Tests for `yertle nodes apply`.

The command exists because push is a full replace: anything missing from the
document is deleted. So the tests that matter are the refusals — a document
that was never read, a branch that moved, and a change that removes
something — because each is a path where applying would quietly destroy
state.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from yertle_client.models import NodeTreeDocument, PushStateResponse

from tests._output import plain
from yertle.cli.main import app

runner = CliRunner()

_GET = "yertle.nodes._tree_document.sync"
_PUSH = "yertle.nodes._push.sync"
_FIXTURES = Path(__file__).parent.parent / "fixtures"
_RAW = json.loads((_FIXTURES / "tree_document_rich.json").read_text())


def _doc() -> NodeTreeDocument:
    return NodeTreeDocument.from_dict(json.loads(json.dumps(_RAW)))


def _written(tmp_path: Path, mutate=None) -> Path:
    raw = json.loads(json.dumps(_RAW))
    if mutate:
        mutate(raw)
    path = tmp_path / "doc.json"
    path.write_text(json.dumps(raw))
    return path


def _result(
    *,
    unchanged: bool = False,
    ignored_keys: list[str] | None = None,
) -> PushStateResponse:
    return PushStateResponse(
        commit_id="c0ffee00-0000-0000-0000-000000000000",
        node_id=str(_RAW["status"]["node_id"]),
        branch="main",
        message="m",
        objects_created=1,
        objects_reused=0,
        unchanged=unchanged,
        ignored_keys=ignored_keys or [],
    )


def _apply(path: Path, *extra: str, push_result: PushStateResponse | None = None):
    with (
        patch(_GET, return_value=_doc()),
        patch(_PUSH, return_value=push_result or _result()) as push,
        patch("yertle._client.get_client", return_value=object()),
    ):
        result = runner.invoke(app, ["nodes", "apply", "-f", str(path), *extra])
    return result, push


def test_refuses_a_document_that_was_never_read(tmp_path: Path) -> None:
    """No base commit means it was assembled by hand — and push replaces all."""
    path = _written(tmp_path, lambda raw: raw.pop("expected_head_commit"))
    result, push = _apply(path)
    assert result.exit_code == 1
    text = plain(result.output)
    assert "not produced by a read" in text
    assert "nodes show" in text
    push.assert_not_called()


def test_refuses_something_that_is_not_a_document(tmp_path: Path) -> None:
    path = tmp_path / "doc.json"
    path.write_text(json.dumps({"hello": "world"}))
    result, push = _apply(path)
    assert result.exit_code == 1
    assert "does not look like a node document" in plain(result.output)
    push.assert_not_called()


def test_refuses_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "doc.json"
    path.write_text("{not json")
    result, _ = _apply(path)
    assert result.exit_code == 1
    assert "not valid JSON" in plain(result.output)


def test_refuses_when_the_branch_moved(tmp_path: Path) -> None:
    """Drift, named as drift — not relayed later as an opaque 409."""
    path = _written(
        tmp_path,
        lambda raw: raw.update(expected_head_commit="00000000-dead-beef-0000-000000000000"),
    )
    result, push = _apply(path)
    assert result.exit_code == 1
    text = plain(result.output)
    assert "branch moved since this document was read" in text
    push.assert_not_called()


def test_refuses_a_removal_without_the_flag(tmp_path: Path) -> None:
    path = _written(tmp_path, lambda raw: raw["state"].update(directories=[]))
    result, push = _apply(path, "-m", "drop dirs")
    assert result.exit_code == 1
    assert "would remove" in plain(result.output)
    push.assert_not_called()


def test_allows_a_removal_with_the_flag(tmp_path: Path) -> None:
    path = _written(tmp_path, lambda raw: raw["state"].update(directories=[]))
    result, push = _apply(path, "-m", "drop dirs", "--allow-deletes")
    assert result.exit_code == 0, result.output
    push.assert_called_once()


def test_dry_run_shows_the_diff_and_writes_nothing(tmp_path: Path) -> None:
    path = _written(tmp_path, lambda raw: raw["state"]["node"].update(title="Renamed"))
    result, push = _apply(path, "--dry-run")
    assert result.exit_code == 0, result.output
    text = plain(result.output)
    assert "title: Yertle Webapp → Renamed" in text
    assert "nothing written" in text
    push.assert_not_called()


def test_dry_run_needs_no_commit_message(tmp_path: Path) -> None:
    """Nothing is written, so demanding a message would be pure friction."""
    path = _written(tmp_path, lambda raw: raw["state"]["node"].update(title="Renamed"))
    result, _ = _apply(path, "--dry-run")
    assert result.exit_code == 0, result.output


def test_a_real_change_needs_a_commit_message(tmp_path: Path) -> None:
    path = _written(tmp_path, lambda raw: raw["state"]["node"].update(title="Renamed"))
    result, push = _apply(path)
    assert result.exit_code == 1
    assert "commit message is required" in plain(result.output)
    push.assert_not_called()


def test_the_documents_own_message_is_used_when_no_flag_is_given(tmp_path: Path) -> None:
    def mutate(raw):
        raw["state"]["node"]["title"] = "Renamed"
        raw["message"] = "from the document"

    result, push = _apply(_written(tmp_path, mutate))
    assert result.exit_code == 0, result.output
    assert push.call_args.kwargs["body"].message == "from the document"


def test_an_unchanged_document_writes_nothing(tmp_path: Path) -> None:
    result, push = _apply(_written(tmp_path))
    assert result.exit_code == 0, result.output
    assert "Nothing to apply" in plain(result.output)
    push.assert_not_called()


def test_ignored_keys_are_surfaced(tmp_path: Path) -> None:
    """The only signal that a typo was silently dropped."""
    path = _written(tmp_path, lambda raw: raw["state"]["node"].update(title="Renamed"))
    result, _ = _apply(
        path, "-m", "x", push_result=_result(ignored_keys=["state.connections[].lable"])
    )
    text = plain(result.output)
    assert "Ignored 1 unknown key" in text
    assert "state.connections[].lable" in text


def test_an_unchanged_push_is_reported_as_such(tmp_path: Path) -> None:
    path = _written(tmp_path, lambda raw: raw["state"]["node"].update(title="Renamed"))
    result, _ = _apply(path, "-m", "x", push_result=_result(unchanged=True))
    assert "Already up to date" in plain(result.output)


def test_apply_takes_its_target_from_the_document(tmp_path: Path) -> None:
    """There is no --org: a document knows which node it belongs to."""
    path = _written(tmp_path, lambda raw: raw["state"]["node"].update(title="Renamed"))
    with (
        patch(_GET, return_value=_doc()) as get,
        patch(_PUSH, return_value=_result()),
        patch("yertle._client.get_client", return_value=object()),
    ):
        runner.invoke(app, ["nodes", "apply", "-f", str(path), "-m", "x"])
    assert get.call_args.kwargs["node_id"] == _RAW["status"]["node_id"]
    assert str(get.call_args.kwargs["org_id"]) == _RAW["status"]["org_id"]


@pytest.mark.parametrize("flag", ["--dry-run", "--allow-deletes"])
def test_flags_are_spelled_as_documented(flag: str) -> None:
    assert flag in plain(runner.invoke(app, ["nodes", "apply", "--help"]).output)
