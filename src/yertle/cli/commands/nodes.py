"""`yertle nodes` — work with nodes."""

from typing import Any

import typer
from yertle_client.models import NodeResponse

import yertle
from yertle.cli._context import OrgOption, resolve_org
from yertle.cli._errors import api_errors
from yertle.cli._render import Column, Format, FormatOption, render

app = typer.Typer(
    name="nodes",
    help="Work with nodes.",
    no_args_is_help=True,
)


def _count(value: Any) -> str:
    """Render an optional count.

    These arrive as `int | None | Unset`; anything that isn't a number means
    the backend didn't compute it for this row, which is different from zero
    and should not be displayed as one.
    """
    return str(value) if isinstance(value, int) else "—"


BASE_COLUMNS: list[Column[NodeResponse]] = [
    Column("ID", lambda node: node.id, style="cyan", no_wrap=True),
    Column("Title", lambda node: node.title),
    Column("Children", lambda node: _count(node.num_children)),
    Column("Parents", lambda node: _count(node.num_parents)),
]

# Only worth a column when the listing spans orgs; when scoped it is the same
# value on every row, and a second 36-character id squeezes the title off an
# 80-column terminal. Short ids will make this cheaper once the id cache lands
# for `nodes show` / `tree`.
ORG_COLUMN: Column[NodeResponse] = Column(
    "Org",
    lambda node: node.org_id,
    style="dim",
    no_wrap=True,
)


@app.command("list")
def list_nodes(org: OrgOption = None, fmt: FormatOption = Format.TABLE) -> None:
    """List nodes in an organization, or across every org you belong to."""
    org_id = resolve_org(org)

    with api_errors():
        nodes = yertle.nodes.list(org_id)

    across_orgs = org_id == yertle.nodes.ALL_ORGS
    scope = "all organizations" if across_orgs else f"org {org_id}"
    render(
        nodes,
        fmt=fmt,
        columns=[*BASE_COLUMNS, ORG_COLUMN] if across_orgs else BASE_COLUMNS,
        title=f"Nodes in {scope} ({len(nodes)})",
    )
