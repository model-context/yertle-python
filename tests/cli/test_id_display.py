"""Text output names ids by their short form, with one exception.

The rule: every org, node and commit id in table or text output is the
8-character short id, which pastes straight back into any command. The one
full UUID is the identity line of a `show` command, the line under the title
naming the thing shown, as `git show` prints a commit's full SHA. `--format
json` is untouched and keeps every id whole.

Each case runs a real command over captured responses and fails if a full
UUID appears anywhere else, so a new line that prints `node.id` is caught
here rather than in someone's terminal.
"""

import re
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from tests._output import plain
from tests._public_api import PublicAPI, install_member, location
from tests._public_api import fixture as public_fixture
from tests._short_ids import FULL_NODE, FULL_ORG, ROOT_NODE, SHORT_NODE, SHORT_ORG, fixture
from yertle.cli.main import app

runner = CliRunner()

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# `tree_document_rich.json` is a real node with children, parents and
# connections: the most ids any one `nodes show` prints.
_RICH = cast(dict[str, Any], public_fixture("../tree_document_rich.json"))
RICH_NODE: str = _RICH["status"]["node_id"]
RICH_ORG: str = _RICH["status"]["org_id"]


@pytest.fixture
def member(public_api: PublicAPI, token: str) -> PublicAPI:
    install_member(public_api, token)
    return public_api


def _full_id_lines(output: str) -> list[int]:
    """Indexes of the lines that carry a full UUID."""
    return [i for i, line in enumerate(output.splitlines()) if UUID.search(line)]


def _run(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.stdout


def test_orgs_show_prints_the_full_id_only_under_the_name(member: PublicAPI) -> None:
    member.serve(f"/orgs/{SHORT_ORG}", fixture("org_member.json"))

    out = _run("orgs", "show", SHORT_ORG)

    assert out.splitlines()[1] == FULL_ORG
    assert _full_id_lines(out) == [1]
    assert f"Root node    {ROOT_NODE[:8]}" in out


def test_nodes_show_prints_the_full_id_only_under_the_title(member: PublicAPI) -> None:
    member.serve(f"/nodes/{RICH_NODE}", location(RICH_NODE, RICH_ORG).to_dict())
    member.serve(f"/orgs/{RICH_ORG}/nodes/{RICH_NODE}/tree/main", _RICH)

    out = _run("nodes", "show", RICH_NODE)

    assert out.splitlines()[1].startswith(RICH_NODE)
    assert _full_id_lines(out) == [1]
    # Parents and children are listed, each with its short id.
    child = _RICH["state"]["visual_properties"][0]["child_node_id"]
    parent = _RICH["status"]["parents"][0]["id"]
    assert child[:8] in out and parent[:8] in out


def test_listings_print_no_full_ids(member: PublicAPI) -> None:
    member.serve(f"/orgs/{SHORT_ORG}/nodes", fixture("nodes.json"))
    member.serve(f"/orgs/{SHORT_ORG}/hierarchy", public_fixture("hierarchy_member.json"))

    for command in (["nodes", "list", "--org", SHORT_ORG], ["nodes", "tree", "--org", SHORT_ORG]):
        out = _run(*command)
        assert _full_id_lines(out) == [], command
        assert f"org {SHORT_ORG}" in out, command


def test_branches_list_names_the_node_by_title_and_short_id(member: PublicAPI) -> None:
    member.serve(f"/nodes/{SHORT_NODE}", fixture("node_location.json"))
    member.serve(f"/orgs/{FULL_ORG}/nodes/{FULL_NODE}/branches", fixture("branches.json"))

    out = _run("branches", "list", SHORT_NODE)

    # Before: "Branches on ab7bd00e-0000-4000-…", wrapped onto two lines.
    assert f"Branches on Payments API {SHORT_NODE} (" in plain(out)
    assert _full_id_lines(out) == []


def test_json_output_keeps_full_ids(member: PublicAPI) -> None:
    member.serve(f"/orgs/{SHORT_ORG}/nodes", fixture("nodes.json"))

    out = _run("nodes", "list", "--org", SHORT_ORG, "--format", "json")

    assert UUID.search(out)
